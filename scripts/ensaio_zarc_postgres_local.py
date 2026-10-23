"""Prova E2E: staging + RAW + PostgreSQL 17 LOCAL, com 27.918 linhas fictícias.

Módulo manual; não lê rede pública, não escreve Neon ou serviços externos.
Requer PostgreSQL loopback e psycopg3 instalados no runner isolado.
"""
from __future__ import annotations
import io
import json
import os
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from time import monotonic

from nivon.catalogo_fontes import carregar_catalogo
from nivon.zarc_raw_vault import guardar_raw_zarc
from nivon.zarc_staging import abrir_zarc_staging, importar_zarc_local
from nivon.zarc_pg_loader_teste import carregar_teste
from scripts.ensaio_staging_zarc_sintetico import dados_ficticios

def main():
    import psycopg
    host=os.environ.get("NIVON_PG_TEST_HOST","")
    if host not in ("127.0.0.1","localhost","::1"):
        raise PermissionError("POSTGRES_TEST_HOST_DEVE_SER_LOOPBACK")
    pw=os.environ.get("NIVON_PG_TEST_PASSWORD")
    if not pw:
        raise PermissionError("SENHA_EPHEMERA_TESTE_NAO_CONFIGURADA")
    start=monotonic()
    rows=dados_ficticios()
    with tempfile.TemporaryDirectory(prefix="nivon-pg-test-") as root:
        temp=Path(root)
        vault=temp/"vault_raw"
        vault.mkdir(mode=0o700)
        with abrir_zarc_staging() as db:
            catalogo=carregar_catalogo()
            a=importar_zarc_local(db,catalogo,io.BytesIO(rows),
                  coletado_em="2026-10-22T19:00:00-04:00")
            b=importar_zarc_local(db,catalogo,io.BytesIO(rows),
                  coletado_em="2026-10-22T20:00:00-04:00")
            guardar_raw_zarc(db=db,arquivo=io.BytesIO(rows),raiz=vault)
            dsn={"host":host,"port":5432,"dbname":"nivon_stage_test",
                 "user":"nivon_test","password":pw,"connect_timeout":5}
            with psycopg.connect(**dsn,autocommit=True) as pg:
                sql=(Path(__file__).resolve().parents[1]/
                        "sql/postgres/002_zarc_mt_staging.sql").read_text(encoding="utf-8")
                with pg.cursor() as cur:
                    cur.execute(sql)
                pg.autocommit=False
                r=carregar_teste(sqlite=db,raiz_raw=vault,
                        sha256=a["sha256"],postgres=pg,executar=True)
                replay=carregar_teste(sqlite=db,raiz_raw=vault,
                        sha256=a["sha256"],postgres=pg,executar=True)
                with pg.cursor() as cur:
                    cur.execute("""SELECT count(*) FROM nivon_agro_staging.zarc_linhas_mt""")
                    count_pg=cur.fetchone()[0]
                    cur.execute("""SELECT count(*) FROM nivon_agro_staging.zarc_coletas""")
                    count_coletas=cur.fetchone()[0]
                    cur.execute("""SELECT count(*) FROM nivon_agro_staging.zarc_edicoes""")
                    count_edicoes=cur.fetchone()[0]
                assert count_pg==27918, count_pg
                assert count_coletas==2 and count_edicoes==1
                assert b["nova_coleta"] and not b["nova_versao"]
                assert replay["linhas_postgres_verificadas"]==27918
    return {
        "estado":"POSTGRES_LOCAL_17_VALIDADO",
        "linhas_sinteticas":27918,
        "linhas_no_postgres":count_pg,
        "replay_sem_duplicacao":True,
        "coletas":count_coletas,"edicoes":count_edicoes,
        "raw_conferido":True,
        "linhas_conteudo_verificado":r["linhas_postgres_verificadas"],
        "rede_apenas_loopback":True,
        "banco_real_alterado":False,
        "custo_externo_contratado":False,
        "segundos":round(monotonic()-start,3),
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
