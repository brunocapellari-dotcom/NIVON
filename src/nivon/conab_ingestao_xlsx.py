"""Ponte de ingestao CONAB: arquivo XLSX da fila -> parser -> store versionado.

Nao efetua HTTP nem pode autorizar sozinho coleta, armazenamento ou publicacao.
Modo real exige gate do catalogo, evidence de direitos e parser oficial
reaproveitado. Parser alternativo somente para fixtures SINTETICAS.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from urllib.parse import urlsplit

from .conab_fila_publicacoes import proximos_arquivos
from .conab_replay_xlsx import reexecutar_xlsx_conab, PARSER_ID
from .progresso_conab_historico import registrar_progresso_local

_MIME='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
_HASH=re.compile(r'^[0-9a-f]{64}$')


class ErroIngestaoConab(ValueError):
    pass


def _instante(instante: str) -> str:
    if not isinstance(instante,str):
        raise ErroIngestaoConab('instante deve ser ISO com fuso')
    try:
        d=datetime.fromisoformat(instante.replace('Z','+00:00'))
    except ValueError as exc:
        raise ErroIngestaoConab('timestamp invalido') from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroIngestaoConab('timestamp sem fuso')
    return d.astimezone(timezone.utc).isoformat()


def _validar_url(url: str,pagina_url: str) -> bool:
    try:
        p=urlsplit(url)
        origem=urlsplit(pagina_url)
    except ValueError:
        return False
    if (p.scheme!='https' or p.hostname!='www.gov.br' or p.username or p.password
            or p.port not in (None,443) or p.query or p.fragment):
        return False
    return p.path.startswith(origem.path.rstrip('/')+'/')


def _row_fila(db, pagina_url: str, url_candidata: str) -> dict:
    """Consulta contra contrato da fila ja validada; ainda SEM anexo real."""
    db.row_factory=sqlite3.Row
    row=db.execute(
        """SELECT pagina_url,tipo,url,hash_html_edicao FROM conab_documentos_candidatos
           WHERE pagina_url=? AND url=? AND tipo='PLANTIO_COLHEITA'
             AND fase='PENDENTE_VALIDACAO'""",
        (pagina_url,url_candidata)).fetchone()
    if row is None:
        raise ErroIngestaoConab('arquivo nao consta na fila de plantio/colheita')
    return dict(row)


def processar_xlsx_local(db: sqlite3.Connection, catalogo: dict, *,
                         pagina_url: str, url_candidata: str, url_arquivo: str,
                         arquivo: bytes, coletado_em: str,
                         modo: str = 'SINTETICO', direitos_armazenamento: bool = False,
                         autorizacoes: frozenset[str] = frozenset(),
                         evidencia_direitos: str | None = None,
                         parser_sintetico=None) -> dict:
    """Roda a etapa de parser + persistencia; nunca carrega URI de rede.

    No modo REAL_AUTORIZADO, aceita apenas parser interno de bytes XLSX,
    valida arquivo URL dentro da mesma edicao e delega gates ao catalogo.
    O resultado nao atesta origem externa e NAO publica.
    """
    if modo not in ('SINTETICO','REAL_AUTORIZADO'):
        raise ErroIngestaoConab('modo desconhecido')
    if modo=='REAL_AUTORIZADO':
        if direitos_armazenamento is not True:
            raise PermissionError('armazenamento CONAB real requer aprovacao explicita')
        if parser_sintetico is not None:
            raise PermissionError('parser injetado nao e permitido para dado real')
        if not {'COLETA','ARMAZENAMENTO'}.issubset(autorizacoes):
            raise PermissionError('direitos especificos ausentes')
    elif direitos_armazenamento or autorizacoes or evidencia_direitos:
        raise ErroIngestaoConab('fixture sintetica nao pode apresentar direitos reais')
    row=_row_fila(db,pagina_url,url_candidata)
    if not _validar_url(url_arquivo,row['pagina_url']):
        raise ErroIngestaoConab('URL anexo fora da pagina oficial registrada')
    if not isinstance(arquivo,bytes) or not 0<len(arquivo)<=20_000_000:
        raise ErroIngestaoConab('arquivo XLSX vazio/maior que limite')
    coleta=_instante(coletado_em)
    digest=sha256(arquivo).hexdigest()
    if not _HASH.fullmatch(digest):
        raise ErroIngestaoConab('SHA invalido')
    parse=parser_sintetico if parser_sintetico is not None else reexecutar_xlsx_conab
    saida=parse(arquivo,sha256_origem=digest,url_origem=url_arquivo,coletado_em=coleta,
                publicado_em=None)
    if not isinstance(saida,dict) or saida.get('raw_sha256')!=digest:
        raise ErroIngestaoConab('parser nao vinculou RAW com hash')
    if modo=='REAL_AUTORIZADO' and saida.get('parser_id')!=PARSER_ID:
        raise ErroIngestaoConab('parser homologado nao identificado')
    semantico=saida.get('mapa_semantico')
    if not isinstance(semantico,dict) or not 1<=len(semantico)<=5000:
        raise ErroIngestaoConab('parser retornou mapa semantico invalido')
    linhas=[]
    for texto in semantico.values():
        if not isinstance(texto,str):
            raise ErroIngestaoConab('registro serializado invalido')
        rowdata=json.loads(texto)
        if not isinstance(rowdata,dict) or 'coleta' in rowdata:
            raise ErroIngestaoConab('registro deve excluir timestamp de coleta')
        if rowdata.get('source_url') != url_arquivo:
            raise ErroIngestaoConab('registro com URL de origem divergente')
        linhas.append({**rowdata,'coleta':coleta})
    # Este gate foi construido anteriormente e impede gravacao REAL quando
    # catalogo oficial ainda esta OFF. Nao bypassar com override.
    registrou=registrar_progresso_local(
        db,catalogo,registros=linhas,
        sha256_origem=digest,bytes_origem=len(arquivo),mime_origem=_MIME,
        coletado_em=coleta,tipo=modo,
        autorizacoes=autorizacoes,evidencia_direitos=evidencia_direitos,
        arquivo_origem=arquivo)
    return {
        'pagina_conab':pagina_url,
        'url_arquivo':url_arquivo,
        'arquivo_sha256':digest,
        'parser_id':saida.get('parser_id'),
        'observacoes':len(linhas),
        'snapshot_local':registrou,
        'publicacao_permitida':False,
        'status':'PROGRESSO_XLSX_NORMALIZADO_EM_STORE_NAO_HOMOLOGADO',
    }
