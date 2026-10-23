"""Carregador transacional de ZARC do staging SQLite para PostgreSQL DE TESTE.

Regras: operação opt-in, exclusivamente origem SINTETICO e servidor LOOPBACK.
Nenhuma conexão é aberta pelo módulo. O chamador fornece psycopg Connection.
Não faz DDL, não habilita coletas, não grava dados reais, não publica.

Para produção será necessário adaptador independente com gates específicos.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .zarc_postgres_bridge import plano_migracao_zarc, iterar_lotes_postgres

LOOPBACK=frozenset({"localhost","127.0.0.1","::1"})
MAX_BATCH=500

class ErroCargaZarc(ValueError):
    pass


def _conexao_isolada(conexao):
    """Impedir acidentalmente a conexão a bancos PTAX/externos."""
    host=getattr(getattr(conexao,"info",None),"host",None)
    if host not in LOOPBACK:
        raise PermissionError("POSTGRES_REAL_BLOQUEADO_TESTE_SOMENTE_LOOPBACK")
    if getattr(conexao,"autocommit",False) is True:
        raise ErroCargaZarc("AUTOCOMMIT_NAO_PERMITIDO")
    if getattr(conexao,"closed",True):
        raise ErroCargaZarc("CONEXAO_FECHADA")


def _utc(value):
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
    except (ValueError,AttributeError) as exc:
        raise ErroCargaZarc("INSTANTE_INVALIDO") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroCargaZarc("INSTANTE_SEM_FUSO")
    return d.astimezone(timezone.utc)


def carregar_teste(*,sqlite:sqlite3.Connection,raiz_raw,sha256,postgres,
                  executar=False,tamanho_lote=500):
    """DDL deve ter sido aplicado previamente num PostgreSQL descartável."""
    if executar is not True:
        raise PermissionError("EXECUCAO_POSTGRES_OFF")
    _conexao_isolada(postgres)
    if type(tamanho_lote) is not int or not 1<=tamanho_lote<=MAX_BATCH:
        raise ErroCargaZarc("BATCH_INVALIDO")
    plano=plano_migracao_zarc(db=sqlite,raiz=raiz_raw,sha256=sha256)
    if plano["tipo_ledger"]!="SINTETICO":
        raise PermissionError("ORIGEM_REAL_NAO_SUPORTADA_POR_CARREGADOR_DE_TESTE")
    edition=sqlite.execute("""SELECT fonte_url,publicado_em,municipios_mt,
               linhas_total,linhas_mt,tamanho_bytes
               FROM zarc_edicoes WHERE sha256=?""",(sha256,)).fetchone()
    if edition is None:
        raise ErroCargaZarc("EDICAO_AUSENTE")
    coletas=sqlite.execute("""SELECT c.coletado_utc FROM nivon_coletas c
        JOIN nivon_snapshots s ON c.snapshot_id=s.id
        WHERE s.dataset_id='ZARC_JANELAS' AND s.sha256=?
        ORDER BY c.coletado_utc""",(sha256,)).fetchall()
    if not coletas:
        raise ErroCargaZarc("EDICAO_SEM_COLETAS")
    sql_edition="""INSERT INTO nivon_agro_staging.zarc_edicoes(
        source_sha256,competencia,schema_version,raw_bytes,
        total_linhas_brasil,linhas_mt,municipios_mt,source_url,
        data_referencia,data_publicacao,raw_object_sha256)
        VALUES (%s,'2026/2027','ZARC_RAW_MT_V1',%s,%s,%s,%s,%s,NULL,%s,%s)
        ON CONFLICT (source_sha256) DO NOTHING"""
    sql_coleta="""INSERT INTO nivon_agro_staging.zarc_coletas(
        source_sha256,coletado_em,tipo,evidencia_direitos)
        VALUES (%s,%s,'SINTETICO',NULL)
        ON CONFLICT(source_sha256,coletado_em) DO NOTHING"""
    sql_linhas="""INSERT INTO nivon_agro_staging.zarc_linhas_mt(
        source_sha256,linha_fisica,municipio_ibge,municipio_sicor,
        cultura_original,cod_cultura,cod_ciclo,cod_solo,cod_clima,
        cod_manejo,cod_nm,portaria_original,chave_logica_sha,
        conteudo_sha,dados_raw,risco_interpretado)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,FALSE)
        ON CONFLICT(source_sha256,linha_fisica) DO NOTHING"""
    enviados=0
    # Uma única transação de banco para edição/coletas/todas as linhas.
    with postgres.transaction():
        with postgres.cursor() as cur:
            cur.execute(sql_edition,(sha256,edition["tamanho_bytes"],
                       edition["linhas_total"],edition["linhas_mt"],
                       edition["municipios_mt"],edition["fonte_url"],
                       edition["publicado_em"],sha256))
            cur.execute("""SELECT raw_bytes,total_linhas_brasil,linhas_mt,
                        municipios_mt,schema_version,raw_object_sha256
                        FROM nivon_agro_staging.zarc_edicoes WHERE source_sha256=%s""",
                        (sha256,))
            val=cur.fetchone()
            esperado=(edition["tamanho_bytes"],edition["linhas_total"],
                      edition["linhas_mt"],edition["municipios_mt"],
                      "ZARC_RAW_MT_V1",sha256)
            if val is None or tuple(val)!=esperado:
                raise ErroCargaZarc("CONFLITO_METADADOS_EDICAO_EXISTENTE")
            cur.executemany(sql_coleta,[(sha256,_utc(x[0])) for x in coletas])
            for batch in iterar_lotes_postgres(db=sqlite,raiz=raiz_raw,
                           sha256=sha256,tamanho_lote=tamanho_lote):
                parametros=[]
                for r in batch:
                    parametros.append((
                        sha256,r["linha_fisica"],r["municipio_ibge"],
                        r["municipio_sicor"],r["cultura_original"],
                        r["cod_cultura"],r["cod_ciclo"],r["cod_solo"],
                        r["cod_clima"],r["cod_manejo"],r["cod_nm"],
                        r["portaria_original"],r["chave_logica_sha"],
                        r["conteudo_sha"],
                        json.dumps(r["dados_raw"],ensure_ascii=False,
                                   sort_keys=True,separators=(",",":")),
                    ))
                cur.executemany(sql_linhas,parametros)
                enviados+=len(parametros)
            if enviados!=plano["linhas_mt"]:
                raise ErroCargaZarc("CONTAGEM_SOURCE_DIVERGENTE")
            cur.execute("""SELECT COUNT(*) FROM nivon_agro_staging.zarc_linhas_mt
                           WHERE source_sha256=%s""",(sha256,))
            gravados=int(cur.fetchone()[0])
            if gravados!=enviados:
                raise ErroCargaZarc("CONTAGEM_POSTGRES_DIVERGENTE")
            cur.execute("""SELECT COUNT(*) FROM nivon_agro_staging.zarc_coletas
                           WHERE source_sha256=%s""",(sha256,))
            ncoletas=int(cur.fetchone()[0])
            if ncoletas!=len(coletas):
                raise ErroCargaZarc("COLETAS_POSTGRES_DIVERGENTES")
            # Confere cada registro da base, inclusive durante replay idempotente.
            cur.execute("""SELECT linha_fisica,conteudo_sha,chave_logica_sha,
                       dados_raw FROM nivon_agro_staging.zarc_linhas_mt
                       WHERE source_sha256=%s ORDER BY linha_fisica""",(sha256,))
            comparados=0
            previous=0
            while True:
                rows=cur.fetchmany(tamanho_lote)
                if not rows:
                    break
                for nr,content_sha,logical_sha,raw in rows:
                    original=sqlite.execute("""SELECT conteudo_sha,chave_logica_sha,
                        dados_raw_json FROM zarc_linhas
                        WHERE sha256=? AND linha_fisica=?""",
                        (sha256,nr)).fetchone()
                    if (nr<=previous or original is None
                            or content_sha!=original[0]
                            or logical_sha!=original[1]
                            or raw!=json.loads(original[2])):
                        raise ErroCargaZarc("CONTEUDO_POSTGRES_DIVERGENTE")
                    previous=nr
                    comparados+=1
            if comparados!=gravados:
                raise ErroCargaZarc("VALIDACAO_POSTGRES_INCOMPLETA")
            cur.execute("""SELECT COUNT(*) FROM nivon_agro_staging.zarc_edicoes
               WHERE source_sha256=%s AND publicavel=FALSE
                 AND apto_backtest=FALSE AND raw_backup_verificado=FALSE
                 AND direitos_revisados=FALSE""",(sha256,))
            if cur.fetchone()[0]!=1:
                raise ErroCargaZarc("PUBLICACAO_TESTE_NAO_BLOQUEADA")
    return {
        "estado":"POSTGRES_LOOPBACK_SINTETICO_APROVADO",
        "dataset_id":"ZARC_JANELAS","sha256":sha256,
        "linhas_staging":plano["linhas_mt"],
        "linhas_postgres_verificadas":comparados,
        "coletas":ncoletas,"replay_seguro":True,
        "servidor_apenas_loopback":True,"nuvem":False,
        "dados_reais":False,"publicavel":False,
    }
