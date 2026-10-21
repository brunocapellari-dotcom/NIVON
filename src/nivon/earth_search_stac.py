"""Earth Search v1 STAC: descoberta pontual de imagens, sem baixar rasters.

Consulta GET pública, AOI controlada e janela curta. Metadados e assets são
referências NÃO confiáveis; nenhum href retornado é acessado automaticamente.
Não confundir imagem com NDVI, produtividade ou observação agronômica.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = "https://earth-search.aws.element84.com/v1/search"
COLECOES = frozenset({"sentinel-2-c1-l2a", "sentinel-1-grd", "landsat-c2-l2",
                      "cop-dem-glo-30", "cop-dem-glo-90"})


class ErroSTAC(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _tempo(s, *, exigido=True):
    if s is None and not exigido:
        return None
    if not isinstance(s, str):
        raise ErroSTAC("timestamp não é string")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroSTAC("timestamp inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroSTAC("timestamp sem fuso horário")
    return d.astimezone(timezone.utc).isoformat()


def planejar_busca(*, bbox: tuple, inicio: str, fim: str,
                   colecao: str = "sentinel-2-c1-l2a", limite: int = 10) -> str:
    if colecao not in COLECOES or type(limite) is not int or not 1 <= limite <= 25:
        raise ErroSTAC("coleção/limite não autorizado")
    if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
        raise ErroSTAC("bbox exige 4 coordenadas")
    if any(type(n) not in (int, float) or not math.isfinite(n) for n in bbox):
        raise ErroSTAC("bbox inválida")
    oeste, sul, leste, norte = bbox
    if not (-180 <= oeste < leste <= 180 and -90 <= sul < norte <= 90):
        raise ErroSTAC("bbox fora da superfície terrestre")
    if leste - oeste > 2 or norte - sul > 2:
        raise ErroSTAC("AOI maior que 2 graus não permitida na consulta única")
    try:
        a, b = date.fromisoformat(inicio), date.fromisoformat(fim)
    except (TypeError, ValueError) as exc:
        raise ErroSTAC("datas de imagem inválidas") from exc
    if (a.isoformat() != inicio or b.isoformat() != fim
            or a > b or (b - a).days > 31):
        raise ErroSTAC("intervalo maior que 32 dias")
    params = {
        "collections": colecao,
        "bbox": ",".join(str(float(x)) for x in bbox),
        "datetime": f"{inicio}T00:00:00Z/{fim}T23:59:59Z",
        "limit": str(limite),
    }
    return BASE + "?" + urlencode(params)


def _unicos(pares):
    doc = {}
    for k, v in pares:
        if k in doc:
            raise ErroSTAC("JSON com chave duplicada")
        doc[k] = v
    return doc


def normalizar_busca(payload: bytes, *, bbox: tuple, inicio: str, fim: str,
                     colecao: str, limite: int, coletado_em: str) -> dict:
    url = planejar_busca(bbox=bbox, inicio=inicio, fim=fim,
                        colecao=colecao, limite=limite)
    coleta = _tempo(coletado_em)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 2_000_000:
        raise ErroSTAC("JSON ausente ou grande demais")
    try:
        dados = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unicos)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroSTAC("JSON inválido") from exc
    if not isinstance(dados, dict) or dados.get("type") != "FeatureCollection":
        raise ErroSTAC("resposta não é FeatureCollection")
    features = dados.get("features")
    if not isinstance(features, list) or len(features) > limite:
        raise ErroSTAC("número de cenas não confere")
    # Nunca seguir links STAC "next" silenciosamente; cursor/paginação dependem de controle.
    links = dados.get("links", [])
    if not isinstance(links, list) or any(not isinstance(link, dict) for link in links):
        raise ErroSTAC("links STAC inválidos")
    tem_mais = any(link.get("rel") == "next" for link in links)
    itens, ids = [], set()
    for feat in features:
        if not isinstance(feat, dict) or feat.get("type") != "Feature":
            raise ErroSTAC("item STAC inválido")
        ident = feat.get("id")
        if not isinstance(ident, str) or not 1 <= len(ident) <= 200 or ident in ids:
            raise ErroSTAC("ID de cena ausente ou duplicado")
        ids.add(ident)
        if feat.get("collection") != colecao:
            raise ErroSTAC("coleção divergente da consulta")
        props = feat.get("properties")
        if not isinstance(props, dict):
            raise ErroSTAC("propriedades STAC ausentes")
        horario = _tempo(props.get("datetime"))
        if not inicio <= horario[:10] <= fim:
            raise ErroSTAC("cena fora da janela")
        cloud = props.get("eo:cloud_cover")
        if cloud is not None and (type(cloud) not in (int, float) or
                                  not math.isfinite(cloud) or not 0 <= cloud <= 100):
            raise ErroSTAC("cobertura de nuvens inválida")
        item_bbox = feat.get("bbox")
        if (not isinstance(item_bbox, list) or len(item_bbox) not in (4, 6)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in item_bbox)):
            raise ErroSTAC("bbox da cena inválida")
        assets = feat.get("assets", {})
        if not isinstance(assets, dict) or len(assets) > 150:
            raise ErroSTAC("catálogo de assets inválido")
        # Apenas chaves de asset, não URLs arbitrárias de dado STAC retornado.
        chaves = []
        for chave, asset in assets.items():
            if (not isinstance(chave, str) or len(chave) > 70
                    or not isinstance(asset, dict) or not isinstance(asset.get("href"), str)):
                raise ErroSTAC("asset inválido")
            chaves.append(chave)
        itens.append({
            "stac_id": ident, "colecao": colecao,
            "data_aquisicao_utc": horario,
            "data_referencia": horario[:10], "competencia": horario[:7],
            "cobertura_nuvens_pct": cloud, "bbox": item_bbox,
            "nomes_bandas_e_assets": sorted(chaves),
            "quantidade_assets": len(chaves), "coleta": coleta,
            "publicacao": None,
            "natureza": "METADADOS_CENA_SATELITE_NAO_METRICA_AGRO",
        })
    return {
        "dataset_id": "EARTH_SEARCH_STAC_CENAS", "fonte_id": "EARTH_SEARCH",
        "url_consulta": url, "colecao": colecao, "itens": itens,
        "total_pagina": len(itens), "tem_proxima_pagina": tem_mais,
        "historico_completo": not tem_mais and len(itens) < limite,
        "coleta": coleta, "sha256_original": hashlib.sha256(payload).hexdigest(),
        "apto_publicacao": False, "dados_raster_baixados": False,
        "estado": "METADADOS_STAC_PONTUAIS_NAO_HOMOLOGADOS",
    }


def consultar_cenas(*, bbox: tuple, inicio: str, fim: str,
                    colecao: str = "sentinel-2-c1-l2a", limite: int = 10,
                    executar: bool = False, abridor=None, instante=None) -> dict:
    url = planejar_busca(bbox=bbox, inicio=inicio, fim=fim,
                        colecao=colecao, limite=limite)
    if executar is not True:
        raise PermissionError("STAC consulta não habilitada sem execução explícita")
    target = urlsplit(url)
    if (target.scheme != "https" or target.hostname != "earth-search.aws.element84.com"
            or target.path != "/v1/search" or target.port not in (None, 443)
            or target.username or target.password or target.fragment):
        raise ErroSTAC("URL não permitida")
    agora = instante if instante is not None else datetime.now(timezone.utc)
    if not isinstance(agora, datetime) or agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroSTAC("hora de coleta sem fuso")
    client = abridor if abridor is not None else build_opener(_SemRedirect())
    req = Request(url, headers={"Accept": "application/geo+json,application/json",
                                "User-Agent": "NIVON/0.1 (pesquisa nao comercial)"})
    with client.open(req, timeout=15) as response:
        if int(response.status) != 200 or response.geturl() != url:
            raise ErroSTAC("resposta HTTP ou redirect inválido")
        mime = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if mime not in ("application/json", "application/geo+json"):
            raise ErroSTAC("resposta não é JSON STAC")
        blob = response.read(2_000_001)
        if len(blob) > 2_000_000:
            raise ErroSTAC("consulta retornou conteúdo excessivo")
    doc = normalizar_busca(blob, bbox=bbox, inicio=inicio, fim=fim,
                          colecao=colecao, limite=limite, coletado_em=agora.isoformat())
    return {"aquisição": {"bytes": len(blob), "sha256": doc["sha256_original"],
                           "coleta": doc["coleta"]}, "dados": doc}
