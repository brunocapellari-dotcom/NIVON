"""Ponte offline SQLite ZARC -> lotes de parâmetros PostgreSQL.

Verifica RAW original contra ledger antes de exportar. Não abre conexão externa,
não executa SQL, não agenda coletas e jamais marca dados como publicáveis.
Cada lote tem no máximo 500 linhas com SHA, posição física e JSON original.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from .zarc_raw_vault import verificar_raw_zarc, ErroRawZarc
from .zarc_stream_mt import COLUNAS

_SHA=re.compile(r"[a-f0-9]{64}\Z")

class ErroPlanoZarc(ValueError):
    pass


def _pares_sem_duplicata(pares):
    d={}
    for k,v in pares:
        if k in d:
            raise ErroPlanoZarc("JSON_CHAVE_DUPLICADA")
        d[k]=v
    return d


def _hash_campos(d):
    body=json.dumps(d,ensure_ascii=False,sort_keys=True,
                    separators=(",",":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _ler_edicao(db,sha):
    return db.execute("""SELECT dataset_id,competencia,tamanho_bytes,
        linhas_total,linhas_mt,municipios_mt,colunas_schema,publicado_em
        FROM zarc_edicoes WHERE sha256=?""",(sha,)).fetchone()


def plano_migracao_zarc(*,db:sqlite3.Connection,raiz,sha256):
    """Roteiro auditável com intenção operacional explicitamente FALSE."""
    if not isinstance(db,sqlite3.Connection):
        raise ErroPlanoZarc("CONEXAO_SQLITE_LOCAL_EXIGIDA")
    if not isinstance(sha256,str) or not _SHA.fullmatch(sha256):
        raise ErroPlanoZarc("SHA_INVALIDO")
    raw=verificar_raw_zarc(db=db,raiz=raiz,sha256=sha256)
    edition=_ler_edicao(db,sha256)
    if edition is None or edition["colunas_schema"]!="ZARC_RAW_MT_V1":
        raise ErroPlanoZarc("SCHEMA_STAGE_INVALIDO")
    linhas=db.execute("""SELECT COUNT(*) FROM zarc_linhas
                            WHERE sha256=?""",(sha256,)).fetchone()[0]
    if linhas!=edition["linhas_mt"]:
        raise ErroPlanoZarc("CONTAGEM_STAGING_INCOMPATIVEL")
    return {
        "dataset_id":"ZARC_JANELAS",
        "raw_sha256":sha256,
        "competencia":edition["competencia"],
        "linhas_mt":linhas,
        "linhas_brasil":edition["linhas_total"],
        "raw_bytes":raw["bytes"],
        "tipo_ledger":raw["ledger_tipo"],
        "raw_verificado":True,
        "schema_destino":"nivon_agro_staging",
        "sql_ddl":"sql/postgres/002_zarc_mt_staging.sql",
        "gravacao_postgres_executada":False,
        "conexao_externa_realizada":False,
        "apto_para_publicacao":False,
        "homologado_para_backtest":False,
        "selecionar_banco_agricola_antes_de_aplicar":True,
    }


def iterar_lotes_postgres(*,db:sqlite3.Connection,raiz,sha256,tamanho_lote=500):
    """Produz lotes brutos para futuro carregador autenticado, SEM enviar.

    Critério idempotente de destino: (source_sha256, linha_fisica).
    """
    if type(tamanho_lote) is not int or not 1<=tamanho_lote<=500:
        raise ErroPlanoZarc("LOTE_FORA_DA_FAIXA")
    plano=plano_migracao_zarc(db=db,raiz=raiz,sha256=sha256)
    cursor=db.execute("""SELECT linha_fisica,chave_logica_sha,conteudo_sha,
       municipio_ibge,municipio_sicor,cultura_original,cod_cultura,
       cod_ciclo,cod_solo,cod_clima,cod_manejo,cod_nm,portaria_original,
       dados_raw_json FROM zarc_linhas WHERE sha256=? ORDER BY linha_fisica""",
       (sha256,))
    emitidas=0
    anterior=0
    while True:
        rows=cursor.fetchmany(tamanho_lote)
        if not rows:
            break
        result=[]
        for r in rows:
            linha=int(r[0])
            if linha<=anterior:
                raise ErroPlanoZarc("ORDEM_FISICA_DIVERGENTE")
            anterior=linha
            try:
                dados=json.loads(r[13],object_pairs_hook=_pares_sem_duplicata)
            except (ValueError,TypeError) as exc:
                raise ErroPlanoZarc("JSON_RAW_INVALIDO") from exc
            if (not isinstance(dados,dict) or set(dados)!=set(COLUNAS)
                    or any(not isinstance(v,str) for v in dados.values())):
                raise ErroPlanoZarc("LAYOUT_DADOS_ORIGINAIS_DIVERGENTE")
            if _hash_campos(dados)!=r[2] or dados["geocodigo"]!=r[3]:
                raise ErroPlanoZarc("LINHA_ALTERADA_SEM_HASH")
            result.append({
                "source_sha256":sha256,"linha_fisica":linha,
                "chave_logica_sha":r[1],"conteudo_sha":r[2],
                "municipio_ibge":r[3],"municipio_sicor":r[4],
                "cultura_original":r[5],"cod_cultura":r[6],
                "cod_ciclo":r[7],"cod_solo":r[8],
                "cod_clima":r[9],"cod_manejo":r[10],
                "cod_nm":r[11],"portaria_original":r[12],
                "dados_raw":dados,"risco_interpretado":False,
                "homologado":False,
            })
        emitidas+=len(result)
        yield result
    if emitidas!=plano["linhas_mt"]:
        raise ErroPlanoZarc("EXPORTACAO_INCOMPLETA")
