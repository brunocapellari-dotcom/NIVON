"""Histórico incremental de IDs RSS/Atom para impedir notícias 'ressuscitadas'.

O RSS atual pode trazer published alterado. A menor data de publicação
já OBSERVADA prevalece; first_seen não é prova da publicação original.
Somente metadados/hashes, sem texto integral ou dados pessoais.
Sem direitos de armazenamento comprovados, falha antes de criar dados.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .briefing_diario import _chave_url
from .lineup_nacional import instante


class ErroHistoricoNoticia(ValueError):
    pass


def _schema(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise ErroHistoricoNoticia("conexão com transação externa ativa")
    conn.execute("""CREATE TABLE IF NOT EXISTS nivon_noticia_memoria (
        fonte_id TEXT NOT NULL, guid_sha256 TEXT NOT NULL,
        url_sha256 TEXT NOT NULL, primeiro_publicado_em TEXT NOT NULL,
        ultimo_publicado_informado_em TEXT NOT NULL,
        primeira_coleta_em TEXT NOT NULL, ultima_coleta_em TEXT NOT NULL,
        revisoes INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(fonte_id,guid_sha256))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nivon_news_url ON nivon_noticia_memoria(fonte_id,url_sha256)")


def registrar_observacoes(conn: sqlite3.Connection, candidatos: list[dict], *,
                         autorizacao_armazenar: dict) -> dict:
    """Rastreia revisões de feeds por GUID e URL. Nunca libera texto para briefing."""
    if not isinstance(candidatos,list) or len(candidatos)>200:
        raise ErroHistoricoNoticia("observações excedem limite por lote")
    _schema(conn)
    # Validar LOTE todo antes do BEGIN. Não confiar em bool por notícia.
    registros=[]
    for item in candidatos:
        if not isinstance(item,dict):
            raise ErroHistoricoNoticia("notícia sem estrutura")
        fid=item.get("fonte_id")
        direito=autorizacao_armazenar.get(fid)
        if (not isinstance(direito,dict) or direito.get("status")!="APROVADA"
                or "ARMAZENAMENTO" not in direito.get("operacoes",[])
                or not direito.get("evidencia_id")):
            raise PermissionError("fonte RSS sem direitos documentados de armazenamento")
        if item.get("estado")!="EXTRAIDO_NAO_CLASSIFICADO_NAO_AUTORIZADO_PARA_PUBLICACAO":
            raise ErroHistoricoNoticia("candidato RSS já manipulado")
        guid=item.get("guid")
        url=item.get("url")
        if not isinstance(guid,str) or not guid or len(guid)>1000:
            raise ErroHistoricoNoticia("GUID inválido")
        if not isinstance(url,str) or urlsplit(url).scheme!="https":
            raise ErroHistoricoNoticia("URL de artigo inválida")
        publicado=instante(item.get("publicado_em_original"))
        coletado=instante(item.get("coletado_em"))
        if publicado>coletado:
            raise ErroHistoricoNoticia("publicação futura em relação à coleta")
        chave_guid=hashlib.sha256(guid.encode()).hexdigest()
        chave_url=hashlib.sha256(_chave_url(url).encode()).hexdigest()
        registros.append((fid,chave_guid,chave_url,publicado.isoformat(),coletado.isoformat()))
    aceitos=[];republicados=0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for fid,guid,url,original,coleta in registros:
            prev=conn.execute("""SELECT guid_sha256,primeiro_publicado_em,
                       ultimo_publicado_informado_em,primeira_coleta_em,revisoes
                       FROM nivon_noticia_memoria
                       WHERE fonte_id=? AND (guid_sha256=? OR url_sha256=?)
                       ORDER BY primeiro_publicado_em LIMIT 1""",(fid,guid,url)).fetchone()
            if not prev:
                conn.execute("""INSERT INTO nivon_noticia_memoria
                    (fonte_id,guid_sha256,url_sha256,primeiro_publicado_em,
                     ultimo_publicado_informado_em,primeira_coleta_em,
                     ultima_coleta_em,revisoes)
                     VALUES (?,?,?,?,?,?,?,0)""",
                     (fid,guid,url,original,original,coleta,coleta))
                aceitos.append({"fonte_id":fid,"guid_sha256":guid,"primeiro_publicado_em":original,
                                "tipo":"PRIMEIRA_OBSERVACAO_NAO_PUBLICAVEL"})
                continue
            velho_guid,primeiro,ultimo,primeira_coleta,revisoes=prev
            if coleta<primeira_coleta:
                raise ErroHistoricoNoticia("coleta retrospectiva requer trilha de backfill separada")
            novo_primeiro=min(primeiro,original)
            conn.execute("""UPDATE nivon_noticia_memoria
                SET primeiro_publicado_em=?, ultimo_publicado_informado_em=?,
                    ultima_coleta_em=?, revisoes=?
                WHERE fonte_id=? AND guid_sha256=?""",
                (novo_primeiro,original,coleta,revisoes+1,fid,velho_guid))
            republicados+=1
            aceitos.append({"fonte_id":fid,"guid_sha256":velho_guid,
                            "primeiro_publicado_em":novo_primeiro,
                            "tipo":"MESMO_EVENTO_DE_FEED_JA_CONHECIDO_NAO_PUBLICAVEL"})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"observacoes":len(aceitos),"republicacoes_ou_revisoes":republicados,
            "resultados":aceitos,"status":"MEMORIA_ATUALIZADA_SEM_PUBLICACAO",
            "nota":"A menor publicação observada não prova data original externa, mas impede rejuvenescimento por RSS posterior."}
