"""Integração real em SQLite local do dossiê sintético CONAB."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
from unittest import TestCase

from nivon.conab_lote_offline import ErroLoteConab, executar_lote_conab
from nivon.conab_staging_sqlite import preparar_staging, gravar_dossie_conab
from test_conab_lote_e2e import _job, _workbook, _zip


class TestStagingSQLiteConab(TestCase):
    def _dossie(self, directory):
        return executar_lote_conab(manifesto={
            "schema_version":"1.0","jobs":[_job(directory)]},base_dir=directory)

    def test_primeira_captura_e_segunda_idempotente(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            doc=self._dossie(base)
            db=sqlite3.connect(":memory:")
            preparar_staging(db)
            a=gravar_dossie_conab(db,doc)
            b=gravar_dossie_conab(db,doc)
            self.assertEqual((a["inseridos"],b["duplicatas_idempotentes"]),(1,1))
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM nivon_conab_staging_documentos").fetchone()[0],1)
            self.assertFalse(b["habilita_backtest"])
            db.close()

    def test_sha_novo_mesma_edicao_preserva_capturas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a=self._dossie(root)
            parts=_workbook()
            parts["xl/worksheets/sheet1.xml"]=parts[
                "xl/worksheets/sheet1.xml"].replace(b"1234.5",b"1235.5")
            new=_zip(parts)
            (root/"boletim.xlsx").write_bytes(new)
            job=_job(root)
            # _job grava o primeiro XLSX novamente; substituição após preparar job.
            (root/"boletim.xlsx").write_bytes(new)
            job["sha256_xlsx_esperado"]=sha256(new).hexdigest()
            b=executar_lote_conab(manifesto={
                "schema_version":"1.0","jobs":[job]},base_dir=root)
            self.assertEqual(b["inspecionados"],1)
            db=sqlite3.connect(":memory:")
            preparar_staging(db)
            gravar_dossie_conab(db,a)
            result=gravar_dossie_conab(db,b)
            self.assertEqual(result["novos_shas_mesma_edicao"],1)
            hashes=db.execute(
                """SELECT arquivo_sha256 FROM nivon_conab_staging_documentos
                WHERE safra='2023/24' ORDER BY id"""
            ).fetchall()
            self.assertEqual(len(hashes),2)
            self.assertNotEqual(hashes[0][0],hashes[1][0])
            self.assertFalse(result["edicao_historica_autenticada"])
            db.close()

    def test_lote_rejeitado_nao_entra_no_banco(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            job=_job(root,bad_sha=True)
            dossier=executar_lote_conab(manifesto={
                "schema_version":"1.0","jobs":[job]},base_dir=root)
            self.assertEqual(dossier["rejeitados"],1)
            db=sqlite3.connect(":memory:")
            preparar_staging(db)
            with self.assertRaisesRegex(ErroLoteConab,"rejeitado"):
                gravar_dossie_conab(db,dossier)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM nivon_conab_staging_documentos").fetchone()[0],0)
            db.close()

    def test_flag_falsificada_nao_vira_dado_historico(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            dossier=self._dossie(root)
            dossier["resultados"][0]["amostra_layout"][
                "edicao_historica_autenticada"]=True
            db=sqlite3.connect(":memory:")
            preparar_staging(db)
            with self.assertRaisesRegex(ErroLoteConab,"promoção"):
                gravar_dossie_conab(db,dossier)
            db.close()

    def test_sqlite_persistente_em_disco_conserva_metadados(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"raw"
            raw.mkdir()
            dossier=self._dossie(raw)
            file=root/"conab_staging.sqlite"
            with sqlite3.connect(str(file)) as db:
                preparar_staging(db)
                gravar_dossie_conab(db,dossier)
            with sqlite3.connect(str(file)) as db:
                record=db.execute(
                    "SELECT classe_status,layout_json FROM nivon_conab_staging_documentos"
                ).fetchone()
            self.assertEqual(record[0],"OFFLINE_SEM_VINTAGE")
            self.assertEqual(json.loads(record[1])["abas_amostradas"],2)
            self.assertFalse(json.loads(record[1])["habilita_treino"])

    def test_cli_end_to_end_sqlite_e_json_em_um_comando(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"raw"
            raw.mkdir()
            manifest=root/"manifest.json"
            output=root/"dossie.json"
            dbfile=root/"staging.sqlite"
            manifest.write_text(json.dumps({
                "schema_version":"1.0","jobs":[_job(raw)]
            }),encoding="utf-8")
            project=Path(__file__).resolve().parents[1]
            env=os.environ.copy()
            env["PYTHONPATH"]=str(project/"src") + os.pathsep + env.get("PYTHONPATH","")
            command=[
                sys.executable,"-m","nivon.conab_lote_offline",
                "--manifest",str(manifest),"--base-dir",str(raw),
                "--out",str(output),"--sqlite",str(dbfile),
            ]
            proc=subprocess.run(command,cwd=project,env=env,
                                text=True,capture_output=True,timeout=30)
            self.assertEqual(proc.returncode,0,proc.stderr)
            d=json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(d["persistencia_staging"]["inseridos"],1)
            self.assertFalse(d["persistencia_staging"]["habilita_publicacao"])
            with sqlite3.connect(str(dbfile)) as db:
                rows=db.execute(
                    """SELECT arquivo_sha256,classe_status
                       FROM nivon_conab_staging_documentos"""
                ).fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0][0],d["resultados"][0]["vinculo"]["arquivo_raw_sha256"])
            self.assertEqual(rows[0][1],"OFFLINE_SEM_VINTAGE")

    def test_cli_com_raw_invalido_retorna_2_e_preserva_dossie(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"raw"
            raw.mkdir()
            manifest=root/"manifest.json"
            out=root/"rejeicoes.json"
            store=root/"staging.sqlite"
            manifest.write_text(json.dumps({
                "schema_version":"1.0","jobs":[_job(raw,bad_sha=True)]
            }),encoding="utf-8")
            project=Path(__file__).resolve().parents[1]
            env=os.environ.copy()
            env["PYTHONPATH"]=str(project/"src") + os.pathsep + env.get("PYTHONPATH","")
            p=subprocess.run([
                sys.executable,"-m","nivon.conab_lote_offline",
                "--manifest",str(manifest),"--base-dir",str(raw),
                "--out",str(out),"--sqlite",str(store)
            ],cwd=project,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,2,p.stderr)
            dossier=json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(dossier["rejeitados"],1)
            self.assertEqual(dossier["persistencia_staging"]["inseridos"],0)
            self.assertEqual(dossier["persistencia_staging"]["estado"],
                             "NAO_PERSISTIDO_LOTE_COM_REJEICOES")
            self.assertFalse(store.exists())
            self.assertFalse(dossier["habilita_publicacao"])

    def test_conflito_de_layout_rejeita_ao_inves_de_sobrescrever(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            dossier=self._dossie(root)
            db=sqlite3.connect(":memory:")
            preparar_staging(db)
            gravar_dossie_conab(db,dossier)
            changed=deepcopy(dossier)
            changed["resultados"][0]["amostra_layout"]["abas"][0][
                "amostra_celulas"][0]["valor"]="FABRICADO"
            with self.assertRaisesRegex(ErroLoteConab,"conflitante"):
                gravar_dossie_conab(db,changed)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM nivon_conab_staging_documentos").fetchone()[0],1)
            db.close()


if __name__=="__main__":
    import unittest
    unittest.main()
