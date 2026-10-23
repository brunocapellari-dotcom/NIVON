"""Aquisição direta de workbook IMEA publicado em origem configurada.

Não existe endpoint padrão presumido: só URL HTTPS específica, verificada
pelo operador (IMEA). Não confundir arquivo histórico de Drive com atualização.
A normalização alimenta a quarentena NIVON sem promover frete/preço canônico.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .coleta_web import FonteWeb, adquirir_fonte
from .imea_legado_pipeline import preparar_lote, persistir_lote_local

OPERACOES = frozenset({"COLETA", "ARMAZENAMENTO", "USO_INTERNO"})
HOSTS = frozenset({"imea.com.br", "www.imea.com.br"})


class ErroImeaRemoto(ValueError):
    pass


def coletar_imea(*, url: str, base: str | Path,
                 autorizacoes: frozenset[str] = frozenset(),
                 evidencia: str | None = None,
                 executar: bool = False, abridor=None,
                 instante: datetime | None = None) -> dict:
    """Baixa workbook de IMEA em HTTPS (sem redirects), valida e persiste RAW."""
    if executar is not True or not OPERACOES.issubset(autorizacoes):
        raise PermissionError("IMEA remoto: COLETA/ARMAZENAMENTO/USO_INTERNO necessarios")
    if not isinstance(evidencia,str) or len(evidencia.strip())<10:
        raise PermissionError("IMEA remoto: referencia de autorizacao ausente")
    if not isinstance(url,str) or len(url)>1500:
        raise ErroImeaRemoto("endpoint nao configurado")
    partes=urlsplit(url)
    if (partes.scheme!="https" or partes.hostname not in HOSTS or
            partes.port not in (None,443) or partes.username or partes.password or partes.fragment):
        raise ErroImeaRemoto("usar apenas endpoint oficial IMEA HTTPS")
    fonte=FonteWeb(
        fonte_id="IMEA_WORKBOOK_LEGADO_STAGING",url=url,
        dominio_autorizado=partes.hostname,formato="XLSX",
        status_direitos="APROVADA",operacoes_permitidas=frozenset({"COLETA"}),
        limite_bytes=25_000_000)
    recebido=adquirir_fonte(fonte,abridor=abridor,instante=instante)
    lote=preparar_lote(
        recebido["conteudo"],origem=url,
        coletado_em=recebido["capturado_em"],
        publicado_em=None)  # Last-Modified nao equivale a data de publicacao.
    pasta=Path(base)
    saida=persistir_lote_local(lote,banco=pasta/"fontes_reais.sqlite",
         pasta_raw=pasta/"raw",tipo="REAL_AUTORIZADO",
         autorizacoes=autorizacoes,evidencia=evidencia)
    return {
        "fonte":"IMEA","status":"RAW_QUARENTENA_LOCAL",
        "observacoes":len(lote["registros"]),
        "novas_observacoes":saida["lote"]["novas_observacoes"],
        "sha256":saida["lote"]["sha256"],
        "estado":"QUARANTINED",
        "bigquery_canonico":False,
        "origem_verificada_por_respondente":url,
        "publicacao_verificada":False,
    }
