"""Expansão NIVON outubro/2026: adaptadores para fontes públicas sob aprovação por operação.

40 contratos descobertos; duas rotas de metadados públicos + uma autenticada com
leitura pontual. Nenhuma coleta periódica, persistência canônica ou publicação.
Endpoints não descobertos explicitamente nunca são adivinhados.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .catalogo_fontes import carregar_catalogo, ErroCatalogo

_IDS = (
    "ARG_SIO_GRANOS", "ARG_BCR_GEA", "ARG_BOLSA_CEREALES", "ARG_BCCBA",
    "ARG_SENASA", "ARG_INDEC", "ARG_BCRA", "ARG_SMN",
    "ARG_MERCADO_GANADERO", "ARG_INTA_GEO", "BR_DERAL", "BR_IEA",
    "BR_EPAGRI_PRECOS", "BR_EPAGRI_CUSTOS", "BR_CCEE_PLD",
    "BR_SIAGAS", "BR_IRGA", "BR_ABRAPA", "BR_EMBRAPA_MLOG",
    "BR_CONSECANA", "WTO_TIMESERIES", "WTO_EPING", "OECD_SDMX",
    "IGC_GOI", "USGS_MINERALS", "UNECE_UNLOCODE", "WB_WITS",
    "UNCTAD_DATA", "EU_AGRIFOOD", "USDA_MMN", "FEWSNET",
    "TERRACLIMATE", "NASA_SMAP", "HYDROBASINS", "HYDROATLAS",
    "GRDC_RUNOFF", "JRC_ASAP", "EU_GDO", "IRI_CLIMATE",
    "EUMETSAT_DATA",
)
FONTES_EXPANSAO = frozenset(_IDS)
LIMITE_BYTES = 512_000
PLANOS_ESTRUTURADOS = {
    "BR_CCEE_PLD": (
        "https://dadosabertos.ccee.org.br/api/3/action/package_show?id=pld_horario",
        "CKAN_METADATA", None
    ),
    "ARG_BCRA": (
        "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias",
        "BCRA_CATALOG", None
    ),
    "USDA_MMN": (
        "https://marsapi.ams.usda.gov/services/v1.2/reports",
        "USDA_REPORT_CATALOG", "NIVON_USDA_MMN_API_KEY"
    ),
}
HOSTS_OFICIAIS = {
    "BR_CCEE_PLD": "dadosabertos.ccee.org.br",
    "ARG_BCRA": "api.bcra.gob.ar",
    "USDA_MMN": "marsapi.ams.usda.gov",
}


class ErroExpansao(ValueError):
    """Metadado inválido, redirecionamento ou resposta incompatível."""


class _SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def listar_fontes(catalogo=None):
    """Exibe o estágio de cada novo dataset, sem operações de rede."""
    doc = carregar_catalogo() if catalogo is None else catalogo
    fontes = {s["id"] for s in doc["sources"]}
    datasets = {d["source_id"]: d for d in doc["datasets"] if d["source_id"] in FONTES_EXPANSAO}
    if not FONTES_EXPANSAO <= fontes or len(datasets) != len(FONTES_EXPANSAO):
        raise ErroExpansao("catálogo não contém todas as 40 fontes")
    return [{
        "source_id": id_,
        "dataset_id": datasets[id_]["id"],
        "stage": datasets[id_]["stage"],
        "priority": datasets[id_]["priority"],
        "adapter": "METADATA_GET" if id_ in PLANOS_ESTRUTURADOS else "DISCOVERY_PENDING",
        "runtime_enabled": False,
    } for id_ in sorted(FONTES_EXPANSAO)]


def planejar(fonte, *, ambiente=None):
    """Constrói um GET estritamente fixado no domínio oficial, sem rede."""
    if fonte not in FONTES_EXPANSAO:
        raise ErroExpansao("fonte fora da expansão")
    if fonte not in PLANOS_ESTRUTURADOS:
        raise PermissionError("endpoint de dados e parser ainda não homologados")
    url, tipo, cred = PLANOS_ESTRUTURADOS[fonte]
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != HOSTS_OFICIAIS[fonte] or
            parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment):
        raise ErroExpansao("URL não está na allowlist")
    headers = {"Accept": "application/json", "User-Agent": "NIVON/0.1 estudo-nao-comercial"}
    if cred:
        env = os.environ if ambiente is None else ambiente
        secret = env.get(cred)
        if not isinstance(secret, str) or not 8 <= len(secret) <= 256:
            raise PermissionError("chave de API não configurada: " + cred)
        # HTTP Basic da documentação USDA: username=API key, senha vazia.
        import base64
        headers["Authorization"] = "Basic " + base64.b64encode((secret + ":").encode()).decode("ascii")
    return {"source_id": fonte, "url": url, "tipo": tipo, "headers": headers}


def consultar(fonte, *, executar=False, abridor=None, instante=None, ambiente=None):
    """Executa um GET pontual de metadados, limitado em bytes e sem redirect.

    O retorno contém proveniência, hash e contagem de catálogo; NÃO são
    observações validadas, homologadas, persistidas ou publicáveis.
    """
    if executar is not True:
        raise PermissionError("COLETA_EXPANSAO_REDE_OFF")
    plano = planejar(fonte, ambiente=ambiente)
    instante = datetime.now(timezone.utc) if instante is None else instante
    if not isinstance(instante, datetime) or instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroExpansao("timestamp sem timezone")
    client = abridor if abridor is not None else build_opener(_SemRedirecionamento())
    req = Request(plano["url"], headers=plano["headers"])
    with client.open(req, timeout=20) as resp:
        if int(resp.status) != 200 or resp.geturl() != plano["url"]:
            raise ErroExpansao("HTTP diferente de 200 ou redirect")
        mime = resp.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if mime not in ("application/json", "text/json", "text/plain", "application/ld+json"):
            raise ErroExpansao("Content-Type inesperado")
        raw = resp.read(LIMITE_BYTES + 1)
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= LIMITE_BYTES:
        raise ErroExpansao("tamanho vazio ou fora do limite")
    try:
        data = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroExpansao("JSON inválido") from exc
    if not isinstance(data, dict):
        raise ErroExpansao("objeto JSON raiz inválido")
    if fonte == "BR_CCEE_PLD":
        if data.get("success") is not True or not isinstance(data.get("result"), dict):
            raise ErroExpansao("resposta CKAN inválida")
        if str(data["result"].get("name", "")).lower() != "pld_horario":
            raise ErroExpansao("pacote CKAN trocado")
        recursos = data["result"].get("resources")
        if not isinstance(recursos, list) or len(recursos) > 1000:
            raise ErroExpansao("lista de recursos inválida")
        n = len(recursos)
    elif fonte == "ARG_BCRA":
        if data.get("status") != 200 and data.get("status") != 0:
            raise ErroExpansao("status BCRA inválido")
        registros = data.get("results")
        if not isinstance(registros, list):
            raise ErroExpansao("results BCRA ausente")
        n = len(registros)
    else:
        registros = data.get("results")
        if not isinstance(registros, list):
            raise ErroExpansao("results USDA ausente")
        n = len(registros)
    return {
        "source_id": fonte, "tipo": plano["tipo"],
        "quantidade_itens_catalogo": n,
        "sha256_original": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "coletado_em": instante.astimezone(timezone.utc).isoformat(),
        "referencia_de_coleta": plano["url"],
        "estado": "METADATA_SAMPLE_SCHEMA_NOT_HOMOLOGATED",
        "persistido": False, "publicavel": False, "homologado": False,
    }
