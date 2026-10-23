"""Raw PTAX no SQLite já usado pelo NIVON; tudo com dados fictícios."""
import sqlite3
import unittest
from datetime import datetime, timezone, timedelta

from nivon.captura_ptax_http import capturar_ptax_odata
from nivon.ptax_raw_sqlite import (
    ErroRawPTAX, guardar_raw_ptax, consultar_raw_ptax_asof,
)
from nivon.registro_snapshots import abrir_registro
from test_captura_ptax_http import PLANO, CAT, TIME, fake


def mock(quando=TIME):
    return capturar_ptax_odata(PLANO,transporte=fake,relogio=lambda:quando)


class TestRawPTAXSQLite(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def salvar(self,capture=None,**kwargs):
        return guardar_raw_ptax(self.db,CAT,
            capture if capture is not None else mock(),**kwargs)

    def test_raw_preservado_e_reconsultado_com_decimal(self):
        r=self.salvar()
        self.assertEqual(r["status"],"RAW_PTAX_ARMAZENADO_LOCAL_SEM_PUBLICACAO")
        self.assertTrue(r["nova_captura"])
        self.assertTrue(r["raw_preservado"])
        antigo=consultar_raw_ptax_asof(self.db,corte=TIME.isoformat(),
                                       incluir_sinteticos=True)
        self.assertEqual(antigo["status"],"RAW_PTAX_ASOF_RECONFERIDO_LOCAL")
        self.assertEqual(antigo["boletins"][0]["cotacao_compra_decimal"],
                         "5.10000")
        self.assertFalse(antigo["apto_backtest_por_publicacao"])
        self.assertFalse(antigo["publicavel"])

    def test_sintetico_invisivel_na_consulta_operacional(self):
        self.salvar()
        r=consultar_raw_ptax_asof(self.db,corte=TIME.isoformat())
        self.assertEqual(r["status"],"SEM_RAW_PTAX_ATE_CORTE")

    def test_repetir_mesmo_snapshot_mesma_coleta_idempotente(self):
        self.salvar()
        novo=self.salvar()
        self.assertFalse(novo["nova_captura"])
        self.assertFalse(novo["nova_versao_snapshot"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_ptax_raw_blobs").fetchone()[0],1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_ptax_raw_capturas").fetchone()[0],1)

    def test_mesmo_raw_duas_coletas_preserva_duas_datas(self):
        self.salvar()
        depois=TIME+timedelta(hours=1)
        segundo=self.salvar(capture=mock(depois))
        self.assertTrue(segundo["nova_captura"])
        self.assertFalse(segundo["nova_versao_snapshot"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_ptax_raw_blobs").fetchone()[0],1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_ptax_raw_capturas").fetchone()[0],2)
        self.assertEqual(consultar_raw_ptax_asof(
            self.db,corte=TIME.isoformat(),incluir_sinteticos=True)["coleta"],
            TIME.isoformat())
        self.assertEqual(consultar_raw_ptax_asof(
            self.db,corte=depois.isoformat(),incluir_sinteticos=True)["coleta"],
            depois.isoformat())

    def test_synthetic_nao_forja_direitos_ou_classe_real(self):
        with self.assertRaises(ErroRawPTAX):
            self.salvar(autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                        evidencia_direitos="DOC_TESTE")
        forged=dict(mock(),tipo="REAL_AUTORIZADO")
        with self.assertRaises(ErroRawPTAX):
            self.salvar(capture=forged)
        forged=dict(mock(),tipo="REAL_AUTORIZADO",
                    origem_execucao="HTTP_HTTPS_BCB_REAL_NAO_HOMOLOGADO")
        with self.assertRaises(PermissionError):
            self.salvar(capture=forged)

    def test_hash_raw_adulterado_detectado_na_entrada(self):
        forged=dict(mock(),raw_bytes=b"alterado")
        with self.assertRaisesRegex(ErroRawPTAX,"divergentes"):
            self.salvar(capture=forged)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_hash_raw_adulterado_detectado_na_saida(self):
        self.salvar()
        self.db.execute("UPDATE nivon_ptax_raw_blobs SET dados=?",
                        (b"adulterado",))
        with self.assertRaisesRegex(ErroRawPTAX,"adulterado"):
            consultar_raw_ptax_asof(
                self.db,corte=TIME.isoformat(),incluir_sinteticos=True)

    def test_metadados_mesma_coleta_divergentes_bloqueados(self):
        self.salvar()
        antigo=mock()
        h=dict(antigo["cabecalhos_http"],etag='"v2"')
        alterado=dict(antigo,cabecalhos_http=h)
        with self.assertRaisesRegex(ErroRawPTAX,"metadados divergentes"):
            self.salvar(capture=alterado)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_ptax_raw_capturas").fetchone()[0],1)

    def test_rollback_salva_transacao_externa(self):
        self.db.execute("CREATE TABLE sentinela (numero INTEGER)")
        self.db.execute("SAVEPOINT externo")
        self.db.execute("INSERT INTO sentinela VALUES (123)")
        self.salvar()
        self.db.execute("ROLLBACK TO SAVEPOINT externo")
        self.db.execute("RELEASE SAVEPOINT externo")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM sentinela").fetchone()[0],0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
        # A tabela também foi criada dentro do SAVEPOINT externo; SQLite
        # faz rollback do próprio DDL, não apenas das linhas.
        self.assertIsNone(self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='nivon_ptax_raw_blobs'").fetchone())

    def test_corte_passado_nao_ve_snapshot_futuro(self):
        self.salvar()
        passado=TIME-timedelta(seconds=1)
        r=consultar_raw_ptax_asof(self.db,corte=passado.isoformat(),
                                 incluir_sinteticos=True)
        self.assertEqual(r["status"],"SEM_RAW_PTAX_ATE_CORTE")


if __name__=="__main__":
    unittest.main()
