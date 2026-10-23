"""Ensaio local sem rede, 27.918 LINHAS ARTIFICIAIS (mesmo volume de MT).

Os geocódigos e valores deste ensaio são inventados intencionalmente: não
representam o ZARC nem podem ser usados em séries, relatórios ou mapas.
Testa escrita, roundtrip, deduplicação, integridade referencial e backup.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import tempfile
from pathlib import Path
from time import monotonic

from nivon.catalogo_fontes import carregar_catalogo
from nivon.zarc_stream_mt import COLUNAS
from nivon.zarc_staging import abrir_zarc_staging, importar_zarc_local

N = 27_918
MUNICIPIOS_FICTICIOS = 142

def dados_ficticios():
    b=io.StringIO()
    writer=csv.DictWriter(b,fieldnames=COLUNAS,delimiter=";",lineterminator="\n")
    writer.writeheader()
    for i in range(N):
        # Códigos apenas formato IBGE: não são municípios verificados.
        row={f:"" for f in COLUNAS}
        row.update({
            "Nome_cultura":"CULTURA_FICTICIA",
            "SafraIni":"2026","SafraFin":"2027",
            "Cod_Cultura":"999","Cod_Ciclo":"20","Cod_Solo":"2",
            "geocodigo":str(5100000+i%MUNICIPIOS_FICTICIOS),
            "UF":"MT","municipio":"MUNICIPIO_SINTETICO",
            "Cod_Clima":"7","Nome_Clima":"FICTICIO",
            "Cod_Outros_Manejos":"1","Nome_Outros_Manejos":"FICTICIO",
            "Produtividade":"0","Cod_NM":"1","Cod_Munic":"777",
            "Cod_Meso":"0","Cod_Micro":"0","Portaria":"FICTICIA_TESTE",
        })
        row.update({f"dec{x}":str(i%3) for x in range(1,37)})
        writer.writerow(row)
    return b.getvalue().encode("utf-8-sig")

def executar():
    catalogo=carregar_catalogo()
    body=dados_ficticios()
    start=monotonic()
    with tempfile.TemporaryDirectory(prefix="nivon-zarc-sintetico-") as d:
        db_path=Path(d)/"stage.sqlite"
        db=abrir_zarc_staging(db_path)
        try:
            primeira=importar_zarc_local(
                db,catalogo,io.BytesIO(body),
                coletado_em="2026-10-22T12:00:00-04:00")
            segunda=importar_zarc_local(
                db,catalogo,io.BytesIO(body),
                coletado_em="2026-10-22T13:00:00-04:00")
            qtd=db.execute("SELECT COUNT(*) FROM zarc_linhas").fetchone()[0]
            snap=db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0]
            capturas=db.execute("SELECT COUNT(*) FROM nivon_coletas").fetchone()[0]
            fk=db.execute("PRAGMA foreign_key_check").fetchall()
            integridade=db.execute("PRAGMA integrity_check").fetchone()[0]
            if (qtd!=N or snap!=1 or capturas!=2 or fk or integridade!="ok"
                or not primeira["nova_versao"] or segunda["nova_versao"]):
                raise RuntimeError("STAGING_SINTETICO_INCONSISTENTE")
            backup_path=Path(d)/"stage_backup.sqlite"
            with sqlite3.connect(str(backup_path)) as target:
                db.backup(target)
            with sqlite3.connect(str(backup_path)) as restored:
                linhas_backup=restored.execute(
                    "SELECT COUNT(*) FROM zarc_linhas").fetchone()[0]
                ledger_backup=restored.execute(
                    "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0]
                check_backup=restored.execute("PRAGMA integrity_check").fetchone()[0]
                if linhas_backup!=N or ledger_backup!=1 or check_backup!="ok":
                    raise RuntimeError("BACKUP_STAGE_INCONSISTENTE")
            elapsed=round(monotonic()-start,3)
            return {
                "tipo":"CARGA_FICTICIA_SEM_FONTE_REAL",
                "dataset":"ZARC_JANELAS",
                "linhas_geradas":N,
                "municipios_ficticios":MUNICIPIOS_FICTICIOS,
                "linhas_stage":qtd,
                "vintages":snap,
                "coletas":capturas,
                "backup_linhas":linhas_backup,
                "sqlite_integrity_check":integridade,
                "chaves_estrangeiras": "OK",
                "duracao_segundos":elapsed,
                "carga_ao_banco_real":False,
                "dados_agricolas_reais":False,
                "custo_adicional_contratado":False,
            }
        finally:
            db.close()

if __name__=="__main__":
    print(json.dumps(executar(),ensure_ascii=False,sort_keys=True))
