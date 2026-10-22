"""Conectores gratuitos pontuais: discovery CKAN, UN Comtrade, STAC, FRED, NCEI, USDA e EIA.

Somente leitura explicitamente autorizada; nenhum cron, persistência ou publicação.
URLs de downloads fornecidas por terceiros são metadados não confiáveis e nunca seguidas.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

class ErroFonteAberta(ValueError):
    pass

CKAN = {
    "MAPA_ZARC": ("dados.agricultura.gov.br", "tabua-de-risco-zoneamento-agricola-de-risco-climatico"),
    "MAPA_SISZARC": ("dados.agricultura.gov.br", "siszarc-sistemas-de-zoneamento-agricola-e-risco-climatico"),
    "MAPA_SIPEAGRO": ("dados.agricultura.gov.br", "sipeagro"),
    "ANTT_CIOT": ("dados.antt.gov.br", "ciot"),
    "ANTT_RNTRC": ("dados.antt.gov.br", "rntrc"),
    "BCB_MDCR": ("dadosabertos.bcb.gov.br", "matrizdadoscreditorural"),
}
CHAVES = {
    "NOAA_CDO": "NIVON_NOAA_CDO_TOKEN",
    "FRED": "NIVON_FRED_API_KEY",
    "USDA_NASS": "NIVON_USDA_NASS_API_KEY",
    "EIA": "NIVON_EIA_API_KEY",
}
FONTES = frozenset(CKAN) | frozenset(CHAVES) | {"UN_COMTRADE_PREVIEW", "COPERNICUS_STAC_CATALOG"}
MAX_BYTES = 1_500_000

class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _int(v, lo, hi):
    if type(v) is not int or not lo <= v <= hi:
        raise ErroFonteAberta("inteiro fora do limite")
    return v

def _token(nome, env):
    v = env.get(nome, "")
    if not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", v):
        raise PermissionError("credencial gratuita ausente: " + nome)
    return v

def planejar(fonte, *, ano=None, reporter=76, hs="1201", fluxo="X",
             serie="DCOILWTICO", inicio="2024-01-01", fim="2024-01-31",
             cultura="SOYBEANS", limite=10, ambiente=None):
    """Plano PRIVADO: não imprimir URLs contendo API key."""
    if fonte not in FONTES:
        raise ErroFonteAberta("fonte fora da whitelist")
    env = os.environ if ambiente is None else ambiente
    headers = {"Accept": "application/json", "User-Agent": "NIVON/0.1 pesquisa-nao-comercial"}
    if fonte in CKAN:
        host, slug = CKAN[fonte]
        url = "https://" + host + "/api/3/action/package_show?" + urlencode({"id": slug})
        tipo = "CKAN_METADATA"
    elif fonte == "COPERNICUS_STAC_CATALOG":
        url = "https://stac.dataspace.copernicus.eu/v1/collections"
        tipo = "STAC_METADATA"
    elif fonte == "UN_COMTRADE_PREVIEW":
        _int(ano, 1990, 2100)
        _int(reporter, 1, 999)
        if hs not in ("1201", "1005", "1001", "3102", "3105", "TOTAL") or fluxo not in ("X", "M"):
            raise ErroFonteAberta("produto ou fluxo não permitido")
        url = "https://comtradeapi.un.org/public/v1/preview/C/A/HS?" + urlencode({
            "reporterCode": reporter, "period": ano, "partnerCode": 0,
            "cmdCode": hs, "flowCode": fluxo})
        tipo = "PREVIEW_NAO_EXAUSTIVO"
    elif fonte == "NOAA_CDO":
        headers["token"] = _token(CHAVES[fonte], env)
        _int(limite, 1, 50)
        url = "https://www.ncei.noaa.gov/cdo-web/api/v2/datasets?" + urlencode({"limit": limite})
        tipo = "METADATA_GRATUITA"
    elif fonte == "FRED":
        key = _token(CHAVES[fonte], env)
        if serie not in ("DCOILWTICO", "DTWEXBGS", "DGS10", "CPIAUCSL", "DEXBZUS"):
            raise ErroFonteAberta("série não autorizada")
        if (not all(isinstance(x, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", x) for x in (inicio, fim))
                or inicio > fim):
            raise ErroFonteAberta("intervalo inválido")
        url = "https://api.stlouisfed.org/fred/series/observations?" + urlencode({
            "series_id": serie, "api_key": key, "file_type": "json",
            "observation_start": inicio, "observation_end": fim, "limit": 100})
        tipo = "SERIE_PUBLICA_CHAVE"
    elif fonte == "USDA_NASS":
        key = _token(CHAVES[fonte], env)
        _int(ano, 1900, 2100)
        if cultura not in ("SOYBEANS", "CORN", "WHEAT", "COTTON"):
            raise ErroFonteAberta("cultura fora do escopo")
        url = "https://quickstats.nass.usda.gov/api/api_GET/?" + urlencode({
            "key": key, "commodity_desc": cultura, "year": ano,
            "agg_level_desc": "NATIONAL", "statisticcat_desc": "PRODUCTION",
            "format": "JSON"})
        tipo = "ESTATISTICA_USDA_CHAVE"
    elif fonte == "EIA":
        key = _token(CHAVES[fonte], env)
        url = "https://api.eia.gov/v2/petroleum/pri/gnd/?" + urlencode({"api_key": key})
        tipo = "METADATA_EIA_CHAVE"
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment or u.port not in (None, 443):
        raise ErroFonteAberta("plano gerou URL insegura")
    return {"fonte": fonte, "url": url, "headers": headers, "tipo": tipo}

def _unico(pares):
    obj = {}
    for k, v in pares:
        if k in obj:
            raise ErroFonteAberta("chave JSON duplicada")
        obj[k] = v
    return obj

def _referencia(url, host):
    """Somente referência ao recurso CKAN, jamais download."""
    if not isinstance(url, str) or len(url) > 1600:
        return None
    u = urlsplit(url)
    if (u.scheme != "https" or u.hostname != host or u.username or u.password or
            u.fragment or u.port not in (None, 443) or u.query or ".." in u.path):
        return None
    return url

def normalizar(payload, *, fonte, coletado_em):
    if fonte not in FONTES or not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_BYTES:
        raise ErroFonteAberta("payload inválido ou excessivo")
    try:
        dt = datetime.fromisoformat(coletado_em.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ErroFonteAberta("instante inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroFonteAberta("instante sem fuso")
    try:
        obj = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unico)
    except (ValueError, UnicodeError) as exc:
        raise ErroFonteAberta("JSON não válido") from exc
    if not isinstance(obj, dict):
        raise ErroFonteAberta("objeto JSON esperado")
    out = {"fonte_id": fonte, "coleta": dt.astimezone(timezone.utc).isoformat(),
           "referencia": None, "publicacao": None, "competencia": None,
           "sha256_original": hashlib.sha256(payload).hexdigest(), "homologado": False,
           "persistido": False, "publicavel": False, "natureza": "METADATA_OU_PREVIEW"}
    if fonte in CKAN:
        if obj.get("success") is not True or not isinstance(obj.get("result"), dict):
            raise ErroFonteAberta("CKAN erro")
        d = obj["result"]
        if d.get("name") != CKAN[fonte][1] or not isinstance(d.get("resources"), list) or len(d["resources"]) > 500:
            raise ErroFonteAberta("dataset CKAN ou recursos inesperados")
        vistos, recursos = set(), []
        for r in d["resources"]:
            if not isinstance(r, dict) or not isinstance(r.get("id"), str) or r["id"] in vistos:
                raise ErroFonteAberta("recurso duplicado/inválido")
            vistos.add(r["id"])
            f = str(r.get("format") or "").upper()
            if f in ("CSV", "JSON", "ZIP", "XLSX", "SHP", "GEOJSON"):
                recursos.append({"id": r["id"], "formato": f, "nome": str(r.get("name") or "")[:150],
                                 "atualizado_em": r.get("last_modified"),
                                 "url_somente_referencia": _referencia(r.get("url"), CKAN[fonte][0])})
        out.update({"tipo": "CKAN_METADATA", "total_recursos": len(d["resources"]),
                    "recursos": recursos, "licenca_declarada": d.get("license_id"),
                    "atualizado_em": d.get("metadata_modified")})
    elif fonte == "COPERNICUS_STAC_CATALOG":
        c = obj.get("collections")
        if not isinstance(c, list) or len(c) > 300:
            raise ErroFonteAberta("STAC collections ausentes/excessivas")
        out.update({"tipo": "STAC_METADATA", "colecoes": [
            d["id"] for d in c if isinstance(d, dict) and isinstance(d.get("id"), str)]})
    elif fonte == "UN_COMTRADE_PREVIEW":
        if not isinstance(obj.get("data"), list) or len(obj["data"]) > 500:
            raise ErroFonteAberta("Comtrade preview incompatível")
        out.update({"tipo": "COMTRADE_PREVIEW", "linhas": len(obj["data"]),
                    "aviso": "amostra limitada, nao equivale ao total"})
    elif fonte == "FRED":
        if not isinstance(obj.get("observations"), list) or len(obj["observations"]) > 100:
            raise ErroFonteAberta("FRED observations incompatíveis")
        out.update({"tipo": "FRED", "linhas": len(obj["observations"])})
    elif fonte == "USDA_NASS":
        if not isinstance(obj.get("data"), list):
            raise ErroFonteAberta("NASS data ausente")
        out.update({"tipo": "NASS", "linhas": len(obj["data"])})
    elif fonte == "NOAA_CDO":
        if not isinstance(obj.get("results"), list):
            raise ErroFonteAberta("NOAA results ausentes")
        out.update({"tipo": "NOAA", "linhas": len(obj["results"])})
    elif fonte == "EIA":
        if not isinstance(obj.get("response"), dict):
            raise ErroFonteAberta("EIA response ausente")
        out.update({"tipo": "EIA_METADATA", "campos": sorted(obj["response"])[:40]})
    return out

def consultar(fonte, *, executar=False, abridor=None, instante=None, **opcoes):
    if executar is not True:
        raise PermissionError("REDE_DESATIVADA_POR_PADRAO")
    plano = planejar(fonte, **opcoes)
    agora = datetime.now(timezone.utc) if instante is None else instante
    if not isinstance(agora, datetime) or agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroFonteAberta("coleta requer timezone")
    req = Request(plano["url"], headers=plano["headers"])
    cliente = abridor if abridor is not None else build_opener(_SemRedirect())
    with cliente.open(req, timeout=15) as resp:
        if int(resp.status) != 200 or resp.geturl() != plano["url"]:
            raise ErroFonteAberta("HTTP ou redirect não aprovado")
        mime = str(resp.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if mime not in ("application/json", "application/geo+json", "application/vnd.api+json"):
            raise ErroFonteAberta("MIME inesperado")
        data = resp.read(MAX_BYTES + 1)
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_BYTES:
            raise ErroFonteAberta("bytes vazios/excessivos")
    return normalizar(data, fonte=fonte,
                      coletado_em=agora.astimezone(timezone.utc).isoformat())
