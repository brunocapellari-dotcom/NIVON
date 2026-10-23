"""NOAA CPC RONI: uma captura HTTPS manual, limitada, com armazenamento RAW.

Diferente de agendador: chama HTTP somente após opt-in por execução, direitos
de coleta+armazenamento declarados, e mantém as snapshots como NÃO HOMOLOGADOS.
Reutiliza roni_store, sem parser/DB paralelos. Testável com transporte falso.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .noaa_roni import ENDPOINT_OFICIAL, MAX_RAW_BYTES, ErroRONI
from .roni_store import executar_lote_roni, panorama_local_roni


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, url):
        return None


def exigir_direitos_catalogo_roni():
    """Bloqueia rede real enquanto catálogo canônico está em CANDIDATE/OFF.

    A evidência textual passada ao CLI jamais substitui aprovação explícita
    e sincronizada no catálogo e no validador de fontes.
    """
    from .catalogo_fontes import carregar_catalogo
    catalog = carregar_catalogo()
    datasets = [x for x in catalog["datasets"] if x["id"] == "NOAA_ENSO_RONI"]
    if len(datasets) != 1:
        raise PermissionError("NOAA RONI precisa de cadastro canônico único")
    item = datasets[0]
    if (item["stage"] != "REAL_SNAPSHOT_TESTED"
            or item["enabled"] is not True
            or item["collection_authorized"] is not True):
        raise PermissionError(
            "NOAA RONI: catálogo CANDIDATE/OFF não autoriza HTTP real; "
            "declaração de licença não pode substituir a homologação")
    return True


def capturar_roni_manual(
    db, *, raw_dir, autorizar_http=False,
    autorizacoes=frozenset(), evidencia_direitos=None,
    confirmar_revisao=False, timeout=15, transporte=None,
):
    """Zero HTTP por padrão; no máximo uma requisição GET se autorizado.

    HTTPS e URL fixos. A evidência de direitos é um registro declaratório,
    não atesta licença. Conteúdo real obtido também NÃO atesta vintages de
    publicações mais antigas, precisão preditiva nem redistribuição.
    """
    if autorizar_http is not True or not {"COLETA", "ARMAZENAMENTO"}.issubset(autorizacoes):
        raise PermissionError("NOAA RONI: coleta e guarda requerem opt-in e direitos")
    if (not isinstance(evidencia_direitos, str) or
        not 12 <= len(evidencia_direitos.strip()) <= 400):
        raise PermissionError("declaração de direitos da fonte não fornecida")
    if type(confirmar_revisao) is not bool or type(timeout) is not int or not 1 <= timeout <= 25:
        raise ErroRONI("parâmetros da captura NOAA incompatíveis")
    # Testes injetam transporte falso; CLI/produção nunca injeta transporte.
    # Qualquer requisição real exige gates do catálogo (que hoje está OFF).
    if transporte is None:
        exigir_direitos_catalogo_roni()
    # Não buscar de novo por padrão se já houver qualquer captura desse arquivo.
    existing = panorama_local_roni(
        db, raw_dir=raw_dir, classe="EXTERNO_NAO_HOMOLOGADO")
    if existing["estado"] != "VAZIO" and not confirmar_revisao:
        return {
            "estado": "CACHE_LOCAL_NENHUMA_REQUISICAO",
            "sha256": existing["sha256_mais_recente"],
            "ultima_competencia": existing["competencia_ultima"],
            "requisições_http": 0,
            "homologado": False, "pode_agendar": False,
        }
    req = Request(
        ENDPOINT_OFICIAL,
        headers={"Accept": "text/plain, text/*;q=0.9, application/octet-stream;q=0.6",
                 "User-Agent": "NIVON/1.0 one-shot scientific RONI"},
        method="GET",
    )
    opener = transporte if transporte is not None else build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as res:
            if getattr(res, "status", None) != 200:
                raise ErroRONI("resposta HTTP RONI não foi 200")
            uri = res.geturl() if hasattr(res, "geturl") else ENDPOINT_OFICIAL
            if uri != ENDPOINT_OFICIAL:
                raise ErroRONI("redirecionamento ou fonte externa ao CPC")
            mime = res.headers.get("Content-Type", "").lower().split(";", 1)[0]
            if mime not in ("text/plain", "application/octet-stream", "text/x-text"):
                raise ErroRONI("CPC retornou MIME não aprovado")
            raw = res.read(MAX_RAW_BYTES + 1)
            etag = res.headers.get("ETag")
            mod = res.headers.get("Last-Modified")
    except ErroRONI:
        raise
    except Exception as exc:
        raise ErroRONI("falha HTTPS CPC RONI; nenhum dado foi homologado") from exc
    if not 10 < len(raw) <= MAX_RAW_BYTES:
        raise ErroRONI("corpo HTTP RONI vazio/excessivo")
    # Real clock after read. An optional HTTP Last-Modified is NOT equivalent
    # to individual release dates and does not change the PIT cutoff.
    now = datetime.now(timezone.utc).isoformat()
    record = executar_lote_roni(
        db, raw_dir=raw_dir, raw=raw, coletado_em=now,
        classe="EXTERNO_NAO_HOMOLOGADO")
    return {
        **record,
        "estado_captura": "HTTPS_PUBLICO_UMA_REQUISICAO_SEM_HOMOLOGACAO",
        "origem_https": ENDPOINT_OFICIAL,
        "cabecalho_etag_declarado": etag,
        "cabecalho_ultima_modificacao_declarado": mod,
        "content_type": mime,
        "resposta_sha256": sha256(raw).hexdigest(),
        "requisições_http": 1,
        "licenca_declarada_nao_auditada": True,
        "direitos_de_redistribuicao_aprovados": False,
        "revisao_explicita": confirmar_revisao,
        "pode_agendar": False,
        "homologado": False,
    }
