"""Amostra CSV oficial ZARC/CIOT a partir de catálogo CKAN verificado.

Dois GETs explícitos e limitados: catálogo, depois UM recurso CSV identificado,
somente se ambos tiverem host e caminho oficial; sem agendamento/persistência.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .fontes_abertas_lote import CKAN, consultar as catalogo_ckan, ErroFonteAberta
from .arquivos_publicos_lote import inspecionar_arquivo, LIMITE_BRUTO

# Estes dois datasets têm licença CC Atribuição publicada nas páginas oficiais.
FONTES_CSV_APROVADAS_PARA_ENSAIO = frozenset({"MAPA_ZARC", "ANTT_CIOT"})
LICENCAS_CC_BY = frozenset({"cc-by", "cc-by-4.0", "cc-by-3.0", "cc-by-2.0",
                           "creative-commons-attribution"})

class ErroCSVCKAN(ValueError):
    pass

class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _alvo(fonte, recurso):
    if not isinstance(recurso, dict) or recurso.get("formato") != "CSV":
        raise ErroCSVCKAN("recurso selecionado não é CSV")
    uri = recurso.get("url_somente_referencia")
    if not isinstance(uri, str):
        raise ErroCSVCKAN("recurso fora de host oficial/indisponível")
    p = urlsplit(uri)
    if (p.scheme != "https" or p.hostname != CKAN[fonte][0]
            or p.username or p.password or p.query or p.fragment
            or p.port not in (None, 443) or
            not p.path.startswith("/dataset/") or
            "/resource/" not in p.path or "/download/" not in p.path or
            not p.path.lower().endswith(".csv")):
        raise ErroCSVCKAN("recurso não tem caminho CSV canônico")
    return uri

def coletar_amostra_csv(*, fonte, recurso_id, executar=False, abridor=None, instante=None):
    if executar is not True:
        raise PermissionError("AMOSTRA_CSV_REDE_OFF")
    if fonte not in FONTES_CSV_APROVADAS_PARA_ENSAIO:
        raise PermissionError("fonte ainda não habilitada para download experimental")
    if not isinstance(recurso_id, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", recurso_id):
        raise ErroCSVCKAN("id do recurso deve ser UUID oficial")
    dt = datetime.now(timezone.utc) if instante is None else instante
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroCSVCKAN("coleta requer timezone")
    client = abridor if abridor is not None else build_opener(_SemRedirect())
    metadata = catalogo_ckan(fonte, executar=True, abridor=client, instante=dt)
    licenca = metadata.get("licenca_declarada")
    if not isinstance(licenca, str) or licenca.strip().lower() not in LICENCAS_CC_BY:
        raise PermissionError("licença declarada não confirmada neste lote")
    matches = [r for r in metadata["recursos"] if r["id"].lower() == recurso_id.lower()]
    if len(matches) != 1:
        raise ErroCSVCKAN("recurso inexistente ou duplicado no catálogo")
    url = _alvo(fonte, matches[0])
    with client.open(Request(url, headers={"Accept": "text/csv,application/csv",
                                           "User-Agent": "NIVON/0.1 nao-comercial"}),
                     timeout=20) as resp:
        if int(resp.status) != 200 or resp.geturl() != url:
            raise ErroCSVCKAN("HTTP/redirect não autorizado")
        mime = str(resp.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if mime not in ("text/csv", "text/plain", "application/csv", "application/octet-stream"):
            raise ErroCSVCKAN("MIME não CSV")
        raw = resp.read(LIMITE_BRUTO + 1)
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= LIMITE_BRUTO:
            raise ErroCSVCKAN("CSV vazio ou maior que limite de teste")
    result = inspecionar_arquivo(fonte, nome="amostra.csv",
                                bytes_brutos=raw,
                                coletado_em=dt.astimezone(timezone.utc).isoformat())
    result.update({"fonte_catalogo_sha": metadata["sha256_original"],
                   "recurso_id": recurso_id, "licenca_catalogo": licenca,
                   "ultima_modificacao_informada": matches[0].get("atualizado_em"),
                   "estado": "CSV_RECEBIDO_SCHEMA_NAO_HOMOLOGADO",
                   "chamadas_http": 2})
    return result
