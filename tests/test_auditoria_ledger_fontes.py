import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from nivon.catalogo_fontes import carregar_catalogo
from nivon.registro_snapshots import abrir_registro, registrar_snapshot
from nivon.auditoria_ledger_fontes import (
    ErroAuditoriaLedger, auditar_cobertura_ledger, main,
)

T = "2026-10-20T12:00:00Z"
T2 = "2026-10-20T14:00:00Z"
SHA = hashlib.sha256(b"PTAX-FIXTURE-SINTETICA").hexdigest()


class TestAuditoriaLedgerFontes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = carregar_catalogo()

    def setUp(self):
        self.db = abrir_registro()
        self.addCleanup(self.db.close)

    def auditar(self, db=True, prioridade="P0", agora="2026-10-20T20:00:00Z"):
        return auditar_cobertura_ledger(
            self.cat, self.db if db else None, prioridade=prioridade, gerado_em=agora,
        )

    def row(self, rel, dataset="BCB_PTAX"):
        return next(x for x in rel["datasets"] if x["dataset_id"] == dataset)

    def gravar_sintetico(self, data=T):
        return registrar_snapshot(
            self.db, self.cat, dataset_id="BCB_PTAX",
            sha256=SHA, tamanho=23, mime="application/json",
            schema_versao="PTAX_TESTE_1", coletado_em=data, tipo="SINTETICO",
        )

    def test_sem_banco_resultado_indeterminado_nao_zero(self):
        r = self.auditar(db=False)
        self.assertIsNone(r["snapshots_sinteticos"])
        self.assertIsNone(r["snapshots_marcados_real"])
        self.assertIsNone(r["capturas_registradas"])
        self.assertIsNone(self.row(r)["capturas"])
        self.assertEqual(self.row(r)["estado"], "SEM_BANCO_NAO_AFERIDO")

    def test_banco_vazio_zero_justificado_apenas_no_ledger(self):
        r = self.auditar()
        self.assertEqual(r["snapshots_sinteticos"], 0)
        self.assertEqual(r["snapshots_marcados_real"], 0)
        self.assertEqual(r["capturas_registradas"], 0)
        self.assertEqual(self.row(r)["estado"], "SEM_SNAPSHOT_NESTE_LEDGER")
        self.assertIsNone(r["volume_observacoes_reais_comprovado"])

    def test_conta_snapshot_e_capturas_separadas(self):
        self.gravar_sintetico()
        self.gravar_sintetico(T2)
        r = self.auditar()
        self.assertEqual(r["snapshots_sinteticos"], 1)
        self.assertEqual(r["capturas_registradas"], 2)
        self.assertEqual(self.row(r)["estado"], "SOMENTE_SINTETICO_NO_LEDGER")
        self.assertEqual(self.row(r)["data_ultima_coleta_utc"],
                         "2026-10-20T14:00:00+00:00")
        self.assertEqual(self.row(r)["competencia_ausente"], 1)
        self.assertEqual(self.row(r)["publicacao_ausente"], 1)

    def test_linha_marcada_real_nao_e_homologacao(self):
        self.db.execute("""INSERT INTO nivon_snapshots
            (dataset_id,fonte_id,sha256,bytes,mime,schema_versao,tipo)
            VALUES (?,?,?,?,?,?,?)""",
            ("BCB_PTAX","BCB",SHA,23,"application/json","FAKE_DB_FIXTURE","REAL_AUTORIZADO"))
        sid = self.db.execute("SELECT id FROM nivon_snapshots").fetchone()[0]
        self.db.execute("INSERT INTO nivon_coletas VALUES (?,?)", (sid,T))
        r = self.auditar()
        self.assertEqual(r["snapshots_marcados_real"], 1)
        self.assertEqual(self.row(r)["estado"], "REAL_DECLARADO_NO_LEDGER_SEM_PROVA_EXTERNA")
        self.assertFalse(self.row(r)["raw_verificado_externamente"])
        self.assertFalse(self.row(r)["pronto_para_publicar"])
        self.assertIsNone(r["volume_observacoes_reais_comprovado"])

    def test_fonte_incorreta_falha_fechada(self):
        self.db.execute("""INSERT INTO nivon_snapshots
            (dataset_id,fonte_id,sha256,bytes,mime,schema_versao,tipo)
            VALUES (?,?,?,?,?,?,?)""",
            ("BCB_PTAX","ANP",SHA,23,"application/json","TEST","SINTETICO"))
        with self.assertRaises(ErroAuditoriaLedger):
            self.auditar()

    def test_dataset_orfao_falha_fechada(self):
        self.db.execute("""INSERT INTO nivon_snapshots
            (dataset_id,fonte_id,sha256,bytes,mime,schema_versao,tipo)
            VALUES (?,?,?,?,?,?,?)""",
            ("DESCONHECIDO","BCB",SHA,23,"application/json","TEST","SINTETICO"))
        with self.assertRaises(ErroAuditoriaLedger):
            self.auditar()

    def test_snapshot_sem_coleta_detectado(self):
        self.db.execute("""INSERT INTO nivon_snapshots
            (dataset_id,fonte_id,sha256,bytes,mime,schema_versao,tipo)
            VALUES (?,?,?,?,?,?,?)""",
            ("BCB_PTAX","BCB",SHA,23,"application/json","TEST","SINTETICO"))
        x = self.row(self.auditar())
        self.assertEqual(x["snapshot_sem_coleta"], 1)
        self.assertEqual(x["estado"], "ANOMALIA_SNAPSHOT_SEM_COLETA")

    def test_coleta_futura_detectada(self):
        self.gravar_sintetico(T2)
        r = self.auditar(agora="2026-10-20T11:00:00Z")
        self.assertEqual(r["problemas"][0]["tipo"], "COLETA_FUTURA")
        self.assertEqual(self.row(r)["estado"], "ANOMALIA_COLETA_FUTURA")

    def test_sem_schema_falha_fechada(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        with self.assertRaises(ErroAuditoriaLedger):
            auditar_cobertura_ledger(self.cat, db)

    def test_prioridade_nao_inventa_snapshot(self):
        r = self.auditar(prioridade="P0")
        self.assertTrue(all(x["prioridade"] == "P0" for x in r["datasets"]))
        self.assertEqual(r["datasets_auditados"], 42)

    def test_timestamp_sem_fuso_recusado(self):
        with self.assertRaises(ErroAuditoriaLedger):
            self.auditar(agora="2026-10-20T12:00:00")

    def test_cli_sem_banco_nao_cria_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "nao-existe.sqlite"
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["--resumo", "--prioridade", "P0"]), 0)
            self.assertFalse(arquivo.exists())
            self.assertIsNone(json.loads(out.getvalue())["capturas_registradas"])

    def test_cli_abre_banco_existente_sem_escrita(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.sqlite"
            db = abrir_registro(str(path))
            db.close()
            size = path.stat().st_size
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["--db", str(path), "--resumo"]), 0)
            self.assertEqual(json.loads(out.getvalue())["capturas_registradas"], 0)
            self.assertEqual(path.stat().st_size, size)

    def test_cli_banco_inexistente_falha_sem_criar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nao.sqlite"
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as erro:
                main(["--db", str(path)])
            self.assertEqual(erro.exception.code, 2)
            self.assertFalse(path.exists())

    def test_cli_rejeita_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "banco.db"
            db = abrir_registro(str(p))
            db.close()
            link = Path(tmp) / "link.db"
            try:
                link.symlink_to(p)
            except (OSError, NotImplementedError):
                self.skipTest("sistema sem suporte a symlinks")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as erro:
                main(["--db", str(link)])
            self.assertEqual(erro.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
