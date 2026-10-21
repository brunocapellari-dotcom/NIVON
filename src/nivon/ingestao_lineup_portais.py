"""Integração snapshot HTTP autorizado -> parser portuário -> resultado auditável.

Permanece OFF por padrão. Não chama sites sem validação de direitos explícita
no nivon.coleta_web. Este módulo permite avaliar aquisições já autorizadas.
"""
from __future__ import annotations

import hashlib

from .coleta_web import FonteWeb, adquirir_fonte
from .lineup_portais import FONTES, ErroPortal, extrair_lineup_portal

URLS = {
    "ITAQUI":"https://www.portodoitaqui.com.br/porto-agora/navios",
    "ARATU":"https://www.codeba.gov.br/eficiente/sites/portalcodeba/pt-br/porto_aratu.php?secao=tportos_aratu",
    "SALVADOR":"https://www.codeba.gov.br/eficiente/sites/portalcodeba/pt-br/site.php?secao=tportos_salvador",
    "ILHEUS":"https://www.codeba.gov.br/eficiente/sites/portalcodeba/pt-br/site.php?secao=tportos_ilheus",
}


def contrato_fonte(porto_id: str) -> FonteWeb:
    if porto_id not in URLS:
        raise ErroPortal("porto não autorizado neste adaptador")
    return FonteWeb(
        fonte_id="LINEUP_"+porto_id, url=URLS[porto_id],
        dominio_autorizado=FONTES[porto_id][0], formato="HTML",
        status_direitos="PENDENTE", operacoes_permitidas=frozenset(),
    )


def processar_snapshot(porto_id: str, snapshot: dict) -> dict:
    """Checa identidade, integridade e charset antes de interpretar HTML."""
    contrato=contrato_fonte(porto_id)
    dados=snapshot.get("conteudo")
    if (snapshot.get("url")!=contrato.url or
            snapshot.get("fonte_id")!=contrato.fonte_id or
            snapshot.get("mime") not in {"text/html","application/xhtml+xml"}):
        raise ErroPortal("identidade MIME e origem do snapshot divergentes")
    if not isinstance(dados,bytes) or not dados or len(dados)>contrato.limite_bytes:
        raise ErroPortal("payload de HTML inválido")
    if hashlib.sha256(dados).hexdigest()!=snapshot.get("sha256"):
        raise ErroPortal("hash de captura não confere")
    try:
        html=dados.decode("utf-8",errors="strict")
    except UnicodeDecodeError as exc:
        raise ErroPortal("HTML requer charset homologado (UTF-8)") from exc
    resultado=extrair_lineup_portal(html,porto_id=porto_id,
                                  fonte_url=contrato.url,
                                  coletado_em=snapshot.get("capturado_em"))
    resultado["sha256"]=snapshot["sha256"]
    resultado["integridade"]="SHA256_CONFERIDO"
    resultado["publicacao_habilitada"]=False
    return resultado


def coletar_autorizado(porto_id: str, *, direitos_comprovados: bool=False,
                      abridor=None) -> dict:
    """Exige direitos humanos verificáveis; não desarma gate por argumento."""
    if not direitos_comprovados:
        raise PermissionError("direitos da fonte não homologados")
    # O contrato permanece fechado. A habilitação exige mudança de governança
    # revisada no cadastro, em vez de um booleano vindo de prompt externo.
    contrato=contrato_fonte(porto_id)
    snapshot=adquirir_fonte(contrato,abridor=abridor)
    return processar_snapshot(porto_id,snapshot)
