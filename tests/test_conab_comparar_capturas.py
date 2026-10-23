"""Integração: captures XLSX sintéticas -> SQLite -> diferença auditável."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
from unittest import TestCase

from nivon.conab_comparar_capturas import (
    comparar_capturas_sqlite, ErroComparacaoCapturas,
)
from nivon.conab_lote_offline import executar_lote_conab
from nivon.conab_staging_sqlite import preparar_staging, gravar_dossie_conab
from test_conab_lote_e2e import _job, _workbook, _zip


def duas_capturas(dbpath, rawfolder):
    job=_job(rawfolder)
    a=executar_lote_conab(manifesto={
        "schema_version":"1.0","jobs":[job]},base_dir=rawfolder)
    base=_workbook()
    base["xl/worksheets/sheet1.xml"]=base[
        "xl/worksheets/sheet1.xml"].replace(b"1234.5",b"1235.5")
    changed=_zip(base)
    (rawfolder/"boletim.xlsx").write_bytes(changed)
    job["sha256_xlsx_esperado"]=sha256(changed).hexdigest()
    b=executar_lote_conab(manifesto={
        "schema_version":"1.0","jobs":[job]},base_dir=rawfolder)
    assert a["inspecionados"]==1 and b["inspecionados"]==1
    with sqlite3.connect(str(dbpath)) as db:
        preparar_staging(db)
        gravar_dossie_conab(db,a)
        gravar_dossie_conab(db,b)
    return a,b


class TestComparacaoCapturasConab(TestCase):
    def test_detecta_um_numero_sem_homologar_revisao(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            source=d/"raw"
            source.mkdir()
            db=d/"staging.sqlite"
            primeira, segunda=duas_capturas(db,source)
            out=comparar_capturas_sqlite(arquivo_sqlite=db)
            self.assertEqual((out["capturas"],out["grupos_edicoes"],out["pares_comparados"]),
                             (2,1,1))
            comp=out["comparacoes"][0]
            self.assertEqual(comp["total_celulas_alteradas_na_amostra"],1)
            self.assertEqual(comp["mudancas_na_amostra"][0]["celula"],"A2")
            self.assertEqual(comp["mudancas_na_amostra"][0]["antes"]["valor"],"1234.5")
            self.assertEqual(comp["mudancas_na_amostra"][0]["depois"]["valor"],"1235.5")
            self.assertFalse(comp["revisao_oficial_conab_comprovada"])
            self.assertFalse(out["comparacao_exaustiva_de_celulas"])
            self.assertFalse(out["habilita_backtest"])
            self.assertFalse(out["habilita_publicacao"])

    def test_estado_vazio_nao_cria_par_fake(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"staging.sqlite"
            with sqlite3.connect(path) as db:
                preparar_staging(db)
            out=comparar_capturas_sqlite(arquivo_sqlite=path)
            self.assertEqual(out["pares_comparados"],0)
            self.assertFalse(out["revisao_oficial_conab_comprovada"])

    def test_rejeita_alteracao_da_classe_na_amostra(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            raw=folder/"raw"
            raw.mkdir()
            dbfile=folder/"staging.sqlite"
            duas_capturas(dbfile,raw)
            with sqlite3.connect(dbfile) as db:
                row=db.execute("SELECT id,layout_json FROM nivon_conab_staging_documentos LIMIT 1").fetchone()
                changed=json.loads(row[1])
                changed["habilita_publicacao"]=True
                db.execute("UPDATE nivon_conab_staging_documentos SET layout_json=? WHERE id=?",
                           (json.dumps(changed),row[0]))
            with self.assertRaisesRegex(ErroComparacaoCapturas,"staging não homologado"):
                comparar_capturas_sqlite(arquivo_sqlite=dbfile)

    def test_db_ausente_eh_erro_nao_cria_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"missing.sqlite"
            with self.assertRaisesRegex(ErroComparacaoCapturas,"ausente"):
                comparar_capturas_sqlite(arquivo_sqlite=db)
            self.assertFalse(db.exists())

    def test_sqlite_apenas_leitura_e_preserva_capturas(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            raw=folder/"raw"
            raw.mkdir()
            dbfile=folder/"staging.sqlite"
            duas_capturas(dbfile,raw)
            size=dbfile.stat().st_size
            comparar_capturas_sqlite(arquivo_sqlite=dbfile)
            self.assertEqual(dbfile.stat().st_size,size)
            with sqlite3.connect(dbfile) as db:
                n=db.execute("SELECT COUNT(*) FROM nivon_conab_staging_documentos").fetchone()[0]
            self.assertEqual(n,2)

    def test_cli_em_lote_gera_diff_uma_vez_sem_atualizar_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            raw=folder/"raw"
            raw.mkdir()
            dbfile=folder/"auditoria #1?.sqlite"
            duas_capturas(dbfile,raw)
            target=folder/"comparacoes.json"
            project=Path(__file__).resolve().parents[1]
            env=os.environ.copy()
            env["PYTHONPATH"]=str(project/"src")+os.pathsep+env.get("PYTHONPATH","")
            command=[sys.executable,"-m","nivon.conab_comparar_capturas",
                     "--sqlite",str(dbfile),"--out",str(target)]
            before=dbfile.stat().st_size
            p=subprocess.run(command,env=env,cwd=project,text=True,
                             capture_output=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr)
            out=json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(out["pares_comparados"],1)
            self.assertFalse(out["revisao_oficial_conab_comprovada"])
            self.assertFalse(out["habilita_treino"])
            self.assertEqual(dbfile.stat().st_size,before)
            again=subprocess.run(command,env=env,cwd=project,text=True,
                                 capture_output=True,timeout=15)
            self.assertEqual(again.returncode,3)

    def test_comparacao_limite_rejeita_booleano(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbfile=Path(tmp)/"staging.sqlite"
            with sqlite3.connect(dbfile) as db:
                preparar_staging(db)
            with self.assertRaisesRegex(ErroComparacaoCapturas,"limite"):
                comparar_capturas_sqlite(arquivo_sqlite=dbfile,limite_mudancas=True)


if __name__=="__main__":
    import unittest
    unittest.main()
