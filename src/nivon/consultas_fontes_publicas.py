"""Consulta HTTPS pontual de INPE focos, CFTC COT e catálogo ANTT CKAN.

Uma operação explícita (executar=True) faz um GET, sem cron/backfill,
sem host arbitrário, sem redirecionamentos, sem persistência ou publicação.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .cftc_cot_publico import planejar_cot, normalizar_cot
from .inpe_queimadas_csv import url_focos_diario, normalizar_focos_diarios

CKAN_SEARCH = "https://dados.antt.gov.br/api/3/action/package_search"


class ErroConsultaPublica(ValueError):
    pass


class _NaoRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_DESTINOS = {
    "cftc": ("publicreporting.cftc.gov", "/resource/72hh-3qpy.json",
             {"application/json", "application/geo+json"}, 1_000_000),
    "inpe": ("dataserver-coids.inpe.br", "/queimadas/queimadas/focos/csv/diario/Brasil/",
             {"text/csv", "text/plain", "application/csv", "application/octet-stream"}, 20_000_000),
    "antt": ("dados.antt.gov.br", "/api/3/action/package_search",
             {"application/json"}, 1_000_000),
}


def _adquirir(*, url: str, fonte: str, executar: bool, abridor=None,
              instante: datetime | None = None) -> dict:
    if executar is not True:
        raise PermissionError("CONSULTA_BLOQUEADA: apenas execução manual explícita")
    if fonte not in _DESTINOS:
        raise ErroConsultaPublica("fonte inexistente na whitelist")
    host, path, formatos, limite = _DESTINOS[fonte]
    u = urlsplit(url)
    if (u.scheme != "https" or u.hostname != host or u.username or u.password
            or u.fragment or u.port not in (None, 443)):
        raise ErroConsultaPublica("HTTPS/host/credenciais incompatíveis")
    if fonte == "inpe":
        if (not u.path.startswith(path) or u.query or not
                u.path.removeprefix(path).startswith("focos_diario_br_") or not
                u.path.endswith(".csv") or "/" in u.path.removeprefix(path)):
            raise ErroConsultaPublica("arquivo INPE fora do padrão")
    elif u.path != path or not u.query:
        raise ErroConsultaPublica("recurso desconhecido")
    agora = instante if instante is not None else datetime.now(timezone.utc)
    if not isinstance(agora, datetime) or agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroConsultaPublica("coleta exige data com fuso")
    cliente = abridor or build_opener(_NaoRedirecionar())
    headers = {"Accept": "text/csv,application/json" if fonte == "inpe" else "application/json",
               "User-Agent": "NIVON/0.1 (pesquisa nao-comercial, fonte publica)"}
    req = Request(url, headers=headers)
    with cliente.open(req, timeout=20) as resp:
        if int(resp.status) != 200 or resp.geturl() != url:
            raise ErroConsultaPublica("HTTP/redirect incompatível")
        mime = str(resp.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if mime not in formatos:
            raise ErroConsultaPublica("MIME inesperado, não aceitar HTML/erro WAF")
        dados = resp.read(limite + 1)
        if not isinstance(dados, bytes) or not 1 <= len(dados) <= limite:
            raise ErroConsultaPublica("resposta vazia ou acima do limite")
    return {"url": url, "corpo": dados, "sha256": hashlib.sha256(dados).hexdigest(),
            "coletado_em": agora.astimezone(timezone.utc).isoformat(), "mime": mime,
            "bytes": len(dados)}


def consultar_cftc(*, data: str, mercado: str, limite: int = 100,
                  executar: bool = False, abridor=None, instante=None) -> dict:
    url = planejar_cot(data=data, mercado=mercado, limite=limite)
    raw = _adquirir(url=url, fonte="cftc", executar=executar,
                    abridor=abridor, instante=instante)
    normal = normalizar_cot(raw["corpo"], data=data, mercado=mercado,
                          limite=limite, coletado_em=raw["coletado_em"])
    return {"aquisição": {k: v for k, v in raw.items() if k != "corpo"}, "dados": normal}


def consultar_inpe_focos(*, data: str, executar: bool = False,
                        abridor=None, instante=None) -> dict:
    url = url_focos_diario(data=data)
    raw = _adquirir(url=url, fonte="inpe", executar=executar,
                    abridor=abridor, instante=instante)
    normal = normalizar_focos_diarios(payload=raw["corpo"], data_arquivo=data,
                                     coletado_em=raw["coletado_em"])
    return {"aquisição": {k: v for k, v in raw.items() if k != "corpo"}, "dados": normal}


def planejar_antt_trafego(*, limite: int = 5) -> str:
    if type(limite) is not int or not 1 <= limite <= 20:
        raise ErroConsultaPublica("limite CKAN inválido")
    return CKAN_SEARCH + "?" + urlencode({"q": "tráfego", "rows": limite,
                                        "start": 0})


def normalizar_antt_catalogo(payload: bytes, *, limite: int, coletado_em: str) -> dict:
    url = planejar_antt_trafego(limite=limite)
    try:
        doc = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroConsultaPublica("CKAN não retornou JSON válido") from exc
    if (not isinstance(doc, dict) or doc.get("success") is not True
            or not isinstance(doc.get("result"), dict)):
        raise ErroConsultaPublica("resposta CKAN sem sucesso")
    result = doc["result"]
    rows = result.get("results")
    total = result.get("count")
    if (not isinstance(rows, list) or len(rows) > limite
            or type(total) is not int or total < len(rows)):
        raise ErroConsultaPublica("paginação CKAN incorreta")
    packages = []
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ErroConsultaPublica("pacote CKAN inválido")
        urls = []
        for res in item.get("resources", []):
            if not isinstance(res, dict):
                raise ErroConsultaPublica("recurso CKAN inválido")
            fmt = res.get("format")
            u = res.get("url")
            if not isinstance(fmt, str) or not isinstance(u, str):
                continue
            uri = urlsplit(u)
            # Apenas REFERÊNCIAS; não abrir URL derivada sem homologar domínio.
            if uri.scheme == "https" and uri.hostname in {"dados.antt.gov.br", "www.gov.br"}:
                urls.append({"formato": fmt.upper(), "url": u})
        packages.append({"id": item["id"], "titulo": item.get("title"),
                         "licenca": item.get("license_id"), "data_modificacao": item.get("metadata_modified"),
                         "recursos_oficiais_candidatos": urls})
    return {"dataset_id": "ANTT_TRAFEGO_CONCESSOES_METADATA", "fonte_id": "ANTT",
            "total_catalogo": total, "pacotes_retorno": packages,
            "consulta_url": url, "coleta": coletado_em,
            "publicacao": None, "apto_publicacao_automatica": False,
            "estado": "DESCOBERTA_METADATA_NAO_FLUXO_REAL_VALIDADO"}


def consultar_antt_trafego(*, limite: int = 5, executar: bool = False,
                          abridor=None, instante=None) -> dict:
    url = planejar_antt_trafego(limite=limite)
    raw = _adquirir(url=url, fonte="antt", executar=executar,
                    abridor=abridor, instante=instante)
    normal = normalizar_antt_catalogo(raw["corpo"], limite=limite,
                                     coletado_em=raw["coletado_em"])
    return {"aquisição": {k: v for k, v in raw.items() if k != "corpo"}, "dados": normal}
