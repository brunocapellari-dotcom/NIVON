"""Cliente pontual OData v2 da Matriz de Dados do Crédito Rural (BCB/SICOR).

Documentação oficial: https://dadosabertos.bcb.gov.br/dataset/matrizdadoscreditorural
Apenas GET em entidades oficiais explicitamente permitidas, $top <= 25,
sem paginação, sem chaves, sem $filter livre e sem persistência/publicação.
A resposta representa AMOSTRA NÃO PROBABILÍSTICA, não crédito total.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

ENDPOINT = "https://olinda.bcb.gov.br/olinda/servico/SICOR/versao/v2/odata/"
ENTIDADES = frozenset({
    "RegiaoUF", "CusteioMunicipioProduto", "InvestMunicipioProduto",
})
MAX_BYTES = 750_000
MAX_TOP = 25


class ErroSicor(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def planejar_sicor(*, entidade="CusteioMunicipioProduto", limite=5):
    """Consulta exploratória estrita, sem filtros arbitrários nem offset."""
    if entidade not in ENTIDADES:
        raise ErroSicor("entidade SICOR não permitida")
    if type(limite) is not int or not 1 <= limite <= MAX_TOP:
        raise ErroSicor("$top fora do limite autorizado")
    url = ENDPOINT + entidade + "?" + urlencode({
        "$top": limite, "$format": "json"
    })
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != "olinda.bcb.gov.br"
            or p.port not in (None, 443) or p.username or p.password or p.fragment):
        raise ErroSicor("origem diferente do BCB")
    return {"url": url, "entidade": entidade, "limite": limite,
            "natureza": "AMOSTRA_SICOR_NAO_TOTAL"}


def _pares(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ErroSicor("JSON com chave duplicada")
        d[k] = v
    return d


def normalizar_sicor(payload, *, entidade, limite, coletado_em):
    planejar_sicor(entidade=entidade, limite=limite)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_BYTES:
        raise ErroSicor("payload SICOR ausente ou acima do limite")
    try:
        coleta = datetime.fromisoformat(coletado_em.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ErroSicor("coleta ISO inválida") from exc
    if coleta.tzinfo is None or coleta.utcoffset() is None:
        raise ErroSicor("coleta precisa ter timezone")
    try:
        doc = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_pares)
    except (UnicodeError, ValueError) as exc:
        raise ErroSicor("JSON SICOR inválido") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("value"), list):
        raise ErroSicor("resposta OData v2 sem value")
    rows = doc["value"]
    if len(rows) > limite:
        raise ErroSicor("resposta maior que $top")
    if "@odata.nextLink" in doc or "odata.nextLink" in doc:
        # Nunca seguir paginação retornada sem contrato e aprovação.
        next_ignored = True
    else:
        next_ignored = False
    if any(not isinstance(r, dict) or len(r) > 90 or
           any(not isinstance(k, str) or len(k) > 120 for k in r)
           for r in rows):
        raise ErroSicor("registro OData incompatível")
    campos = sorted(set().union(*(r.keys() for r in rows))) if rows else []
    return {
        "dataset_id": "BCB_SICOR_MDCR_AMOSTRA", "source_id": "BCB",
        "entidade": entidade, "registros_recebidos": len(rows),
        "campos_declarados": campos,
        "paginacao_bloqueada": next_ignored,
        "sha256_original": hashlib.sha256(payload).hexdigest(),
        "coleta": coleta.astimezone(timezone.utc).isoformat(),
        "publicacao": None, "competencia": None, "referencia": None,
        "licenca_fonte": "ODbL - verificar obrigações de atribuição e share-alike",
        "natureza": "AMOSTRA_NAO_REPRESENTATIVA",
        "valores_monetarios_homologados": False,
        "publicavel": False, "persistido": False,
        "estado": "ODATA_AMOSTRA_PARSEADA_SEM_SCHEMA_CIENTIFICO",
    }


def consultar_sicor(*, entidade="CusteioMunicipioProduto", limite=5,
                    executar=False, abridor=None, instante=None):
    if executar is not True:
        raise PermissionError("REDE_OFF_POR_PADRAO")
    plano = planejar_sicor(entidade=entidade, limite=limite)
    t = datetime.now(timezone.utc) if instante is None else instante
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ErroSicor("instante da coleta sem fuso")
    cliente = abridor if abridor is not None else build_opener(_SemRedirect())
    req = Request(plano["url"], headers={
        "Accept": "application/json",
        "User-Agent": "NIVON/0.1 pesquisa-nao-comercial"
    })
    with cliente.open(req, timeout=15) as resp:
        if int(resp.status) != 200 or resp.geturl() != plano["url"]:
            raise ErroSicor("HTTP/redirect incompatível")
        mime = str(resp.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if mime not in ("application/json", "application/geo+json"):
            raise ErroSicor("resposta SICOR não é JSON")
        corpo = resp.read(MAX_BYTES + 1)
        if not isinstance(corpo, bytes) or not 1 <= len(corpo) <= MAX_BYTES:
            raise ErroSicor("tamanho SICOR incompatível")
    out = normalizar_sicor(
        corpo, entidade=entidade, limite=limite,
        coletado_em=t.astimezone(timezone.utc).isoformat())
    out["consulta_url"] = plano["url"]
    return out
