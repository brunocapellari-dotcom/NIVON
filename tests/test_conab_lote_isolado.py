"""Testes de integração do worker Linux, com dados CONAB SINTÉTICOS."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest import TestCase, mock, skipUnless

from nivon.conab_lote_isolado import (
    ErroIsolamentoConab, executar_worker_conab,
)
from test_conab_lote_e2e import _job

LINUX = sys.platform == "linux" and os.name == "posix"


@skipUnless(LINUX, "limites de processo somente Linux")
class TestWorkerCONAB(TestCase):
    def test_worker_processa_lote_e_persiste_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"raw"
            raw.mkdir()
            jobs=root/"jobs.json"
            out=root/"dossie.json"
            dbfile=root/"staging.sqlite"
            jobs.write_text(json.dumps({"schema_version":"1.0",
                                        "jobs":[_job(raw)]}),encoding="utf-8")
            result=executar_worker_conab(
                manifesto=str(jobs),base_dir=str(raw),saida=str(out),
                sqlite=str(dbfile),timeout_s=25,
            )
            self.assertEqual(result["exit_code"],0,result["stderr"])
            self.assertTrue(result["limites_aplicados"])
            self.assertFalse(result["isolamento_de_rede_aplicado"])
            dossier=json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(dossier["inspecionados"],1)
            self.assertEqual(dossier["persistencia_staging"]["inseridos"],1)
            self.assertFalse(dossier["habilita_publicacao"])
            with sqlite3.connect(dbfile) as db:
                row=db.execute("SELECT classe_status FROM nivon_conab_staging_documentos").fetchone()
            self.assertEqual(row[0],"OFFLINE_SEM_VINTAGE")

    def test_worker_rejeita_sha_invalido_sem_persistir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"raw"
            raw.mkdir()
            jobs=root/"jobs.json"
            out=root/"rejeitados.json"
            dbfile=root/"staging.sqlite"
            jobs.write_text(json.dumps({"schema_version":"1.0",
                                        "jobs":[_job(raw,bad_sha=True)]}),encoding="utf-8")
            result=executar_worker_conab(
                manifesto=str(jobs),base_dir=str(raw),saida=str(out),
                sqlite=str(dbfile),timeout_s=25,
            )
            self.assertEqual(result["exit_code"],2,result["stderr"])
            self.assertEqual(json.loads(out.read_text())["rejeitados"],1)
            self.assertFalse(dbfile.exists())

    def test_worker_nao_reusa_dossie_existente(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"raw"
            raw.mkdir()
            jobs=root/"jobs.json"
            out=root/"dossie.json"
            jobs.write_text(json.dumps({"schema_version":"1.0",
                                        "jobs":[_job(raw)]}),encoding="utf-8")
            args=dict(manifesto=str(jobs),base_dir=str(raw),saida=str(out),timeout_s=25)
            self.assertEqual(executar_worker_conab(**args)["exit_code"],0)
            self.assertEqual(executar_worker_conab(**args)["exit_code"],3)
            self.assertFalse(json.loads(out.read_text())["habilita_backtest"])

    def test_worker_nao_herda_credenciais_ambiente(self):
        import nivon.conab_lote_isolado as mod
        with mock.patch.dict(os.environ,{"NIVON_PRIVATE_TOKEN":"nao-herdar"}):
            original = mod.subprocess.Popen
            def examinar(args, **kwargs):
                self.assertNotIn("NIVON_PRIVATE_TOKEN",kwargs["env"])
                self.assertEqual(args[1:3],["-m","nivon.conab_lote_offline"])
                # apenas inspeciona o launcher; não há acesso à rede
                class Child:
                    pid = 999999
                    returncode = 3
                    def communicate(self,timeout=None):
                        return ("","erro sintético")
                return Child()
            with mock.patch.object(mod.subprocess,"Popen",side_effect=examinar):
                result=executar_worker_conab(
                    manifesto="/tmp/a",base_dir="/tmp/raw",saida="/tmp/b",timeout_s=5
                )
        self.assertEqual(result["exit_code"],3)

    def test_timeout_invalido_falha_antes_de_executar(self):
        for timeout in (0,4,91,True,5.5):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ErroIsolamentoConab):
                    executar_worker_conab(
                        manifesto="/tmp/a",base_dir="/tmp/raw",
                        saida="/tmp/b",timeout_s=timeout
                    )


if __name__=="__main__":
    import unittest
    unittest.main()
