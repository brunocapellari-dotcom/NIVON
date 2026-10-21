"""SOILGRIDS ISRIC v2: consulta PONTUAL de estimativa de solo, sem receita.

Provedor oferece propriedade de solo MODELADA em pixel 250m com incerteza,
não observação de laboratório da fazenda. API REST beta: 5 req/min
(fair-use), sem disponibilidade garantida. Uma consulta explícita, sem cron.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


BASE = "https://rest.isric.org/soilgrids/v2.0/properties/query"
PROPRIEDADES = frozenset({"phh2o", "clay", "sand", "silt", "soc", "nitrogen", "bdod", "cec"})
PROFUNDIDADES = frozenset({"0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"})
ESTIMATIVAS = frozenset({"mean", "Q05", "Q50", "Q95"})


class ErroSoilGrids(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def planejar_solo(*, latitude: float, longitude: float, propriedade: str,
                 profundidade: str = "0-5cm", estimativa: str = "mean") -> str:
    if (type(latitude) not in (int, float) or type(longitude) not in (int, float)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ErroSoilGrids("coordenadas inválidas")
    if propriedade not in PROPRIEDADES or profundidade not in PROFUNDIDADES or estimativa not in ESTIMATIVAS:
        raise ErroSoilGrids("camada/profundidade/estatística não permitida")
    qs = urlencode({"lat": str(latitude), "lon": str(longitude),
                    "property": propriedade, "depth": profundidade, "value": estimativa})
    return BASE + "?" + qs


def _pares(items):
    d = {}
    for k, v in items:
        if k in d:
            raise ErroSoilGrids("JSON com chave duplicada")
        d[k] = v
    return d


def normalizar_solo(payload: bytes, *, latitude: float, longitude: float,
                   propriedade: str, profundidade: str, estimativa: str,
                   coletado_em: str) -> dict:
    u = planejar_solo(latitude=latitude, longitude=longitude,
                      propriedade=propriedade, profundidade=profundidade,
                      estimativa=estimativa)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 300_000:
        raise ErroSoilGrids("JSON ausente ou muito grande")
    try:
        coleta = datetime.fromisoformat(coletado_em.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ErroSoilGrids("coleta inválida") from exc
    if coleta.tzinfo is None or coleta.utcoffset() is None:
        raise ErroSoilGrids("coleta sem fuso")
    try:
        obj = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_pares)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroSoilGrids("JSON inválido") from exc
    if not isinstance(obj, dict):
        raise ErroSoilGrids("resposta não é objeto")
    props = obj.get("properties")
    layers = props.get("layers") if isinstance(props, dict) else None
    if not isinstance(layers, list) or not layers:
        raise ErroSoilGrids("layers de solo ausentes")
    layer = next((x for x in layers if isinstance(x, dict) and x.get("name") == propriedade), None)
    if layer is None:
        raise ErroSoilGrids("camada não retornada")
    unit = layer.get("unit_measure")
    if not isinstance(unit, dict):
        raise ErroSoilGrids("unit_measure ausente")
    factor = unit.get("d_factor")
    target = unit.get("target_units")
    if (type(factor) not in (float, int) or not math.isfinite(factor)
            or factor <= 0 or not isinstance(target, str) or not target):
        raise ErroSoilGrids("fator/unidade física não válidos")
    depth = next((x for x in layer.get("depths", [])
                  if isinstance(x, dict) and x.get("label") == profundidade), None)
    if depth is None or not isinstance(depth.get("values"), dict):
        raise ErroSoilGrids("profundidade não retornada")
    value = depth["values"].get(estimativa)
    if value is not None and (type(value) not in (float, int) or not math.isfinite(value)):
        raise ErroSoilGrids("estimativa não numérica")
    bruto = value
    ajustado = None if bruto is None else bruto / factor
    if ajustado is not None:
        if propriedade == "phh2o" and not (0 <= ajustado <= 14):
            raise ErroSoilGrids("pH fora de faixa física")
        if propriedade in ("clay", "sand", "silt") and ajustado < 0:
            raise ErroSoilGrids("fração granulométrica negativa")
    geom = obj.get("geometry")
    coords = geom.get("coordinates") if isinstance(geom, dict) else None
    if coords is not None:
        if (not isinstance(coords, list) or len(coords) < 2
                or type(coords[0]) not in (int, float) or type(coords[1]) not in (int, float)
                or not math.isfinite(coords[0]) or not math.isfinite(coords[1])
                or abs(coords[0] - longitude) > .3 or abs(coords[1] - latitude) > .3):
            raise ErroSoilGrids("pixel fora da posição solicitada")
    return {
        "dataset_id": "ISRIC_SOILGRIDS_PONTO", "fonte_id": "ISRIC_SOILGRIDS",
        "consulta_url": u, "propriedade": propriedade, "profundidade": profundidade,
        "estatistica": estimativa, "valor_bruto": bruto, "divisor_unidade": factor,
        "valor_fisico_estimado": ajustado, "unidade_fisica": target,
        "latitude_consultada": latitude, "longitude_consultada": longitude,
        "coleta": coleta.astimezone(timezone.utc).isoformat(),
        "referencia": None, "publicacao": None, "competencia": None,
        "natureza": "ESTIMATIVA_SOLO_MODELO_250M_NAO_AMOSTRA_LABORATORIAL",
        "sha256_original": hashlib.sha256(payload).hexdigest(),
        "apto_recomendacao_agronomica": False,
        "apto_publicacao_automatica": False,
        "estado": "RESP_SOILGRIDS_OFFLINE_NAO_HOMOLOGADA",
    }


def consultar_solo(*, latitude: float, longitude: float, propriedade: str,
                   profundidade: str = "0-5cm", estimativa: str = "mean",
                   executar: bool = False, abridor=None, instante=None) -> dict:
    url = planejar_solo(latitude=latitude, longitude=longitude,
                        propriedade=propriedade, profundidade=profundidade,
                        estimativa=estimativa)
    if executar is not True:
        raise PermissionError("CONSULTA_DESATIVADA_SEM_FLAG_EXECUTAR")
    u = urlsplit(url)
    if (u.scheme != "https" or u.hostname != "rest.isric.org"
            or u.path != "/soilgrids/v2.0/properties/query" or u.port not in (None, 443)
            or u.username or u.password or u.fragment):
        raise ErroSoilGrids("host/caminho não autorizado")
    agora = instante if instante is not None else datetime.now(timezone.utc)
    if not isinstance(agora, datetime) or agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroSoilGrids("coleta sem timestamp UTC")
    client = abridor if abridor is not None else build_opener(_SemRedirect())
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "NIVON/0.1 (nao comercial)"})
    with client.open(req, timeout=15) as resp:
        if int(resp.status) != 200 or resp.geturl() != url:
            raise ErroSoilGrids("HTTP/redirect não autorizado")
        mime = str(resp.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if mime != "application/json":
            raise ErroSoilGrids("MIME incompatível")
        raw = resp.read(300_001)
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= 300_000:
            raise ErroSoilGrids("resposta vazia ou muito grande")
    result = normalizar_solo(raw, latitude=latitude, longitude=longitude,
                            propriedade=propriedade, profundidade=profundidade,
                            estimativa=estimativa, coletado_em=agora.isoformat())
    return {"aquisição": {"coleta": agora.astimezone(timezone.utc).isoformat(),
                           "sha256": result["sha256_original"], "bytes": len(raw)},
            "dados": result}
