"""A quarentena PTAX não libera GCS, ledger ou briefing por padrão."""
import sqlite3
import unittest
from hashlib import sha256

from nivon.ptax_quarentena_coleta import receber_amostra_ptax,ErroQuarentenaPTAX
from nivon.ptax_google_cloud import (
    preparar_objetos_gcs_ptax,enviar_objetos_gcs_ptax,ErroExportacaoPTAX,
)
from scripts.ensaio_quarentena_ptax_gcs import RAW,manifesto


class TestQuarentenaE2E(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")

    def test_sem_rede_gera_raw_e_manifesto_consistentes(self):
        r=receber_amostra_ptax(self.db,raw=RAW,manifesto=manifesto())
        pack=preparar_objetos_gcs_ptax(
            self.db,evento_sha256=r["evento_sha256"],
            bucket="nivon-ptax-testes-offline",
        )
        self.assertEqual(len(pack["objetos"]),2)
        self.assertEqual(pack["objetos"][0]["bytes"],RAW)
        for item in pack["objetos"]:
            self.assertEqual(sha256(item["bytes"]).hexdigest(),item["sha256"])
        self.assertFalse(pack["upload_executado"])
        with self.assertRaises(PermissionError):
            enviar_objetos_gcs_ptax(pack)

    def test_raw_falso_ou_evento_ausente_nao_entra_na_quarentena(self):
        bad=manifesto()
        bad["raw_sha256"]="0"*64
        with self.assertRaises(ErroQuarentenaPTAX):
            receber_amostra_ptax(self.db,raw=RAW,manifesto=bad)
        with self.assertRaises(ErroExportacaoPTAX):
            preparar_objetos_gcs_ptax(
                self.db,evento_sha256="f"*64,
                bucket="nivon-ptax-testes-offline",
            )

    def test_status_http_invalido_e_html_waf_nao_homologa(self):
        for change in ({"status_http":403},{"fonte_declarada":"DESCONHECIDA"}):
            v=manifesto();v.update(change)
            with self.subTest(change=change),self.assertRaises(ErroQuarentenaPTAX):
                receber_amostra_ptax(self.db,raw=RAW,manifesto=v)
        invalid=b"<html>WAF request rejected</html>"
        v=manifesto()
        v["raw_sha256"]=sha256(invalid).hexdigest()
        v["cabecalhos_http"]["content-length"]=str(len(invalid))
        with self.assertRaises(ErroQuarentenaPTAX):
            receber_amostra_ptax(self.db,raw=invalid,manifesto=v)

    def test_nao_cria_ledger_operacional_independentemente_de_repeticao(self):
        for _ in range(3):
            receber_amostra_ptax(self.db,raw=RAW,manifesto=manifesto())
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM nivon_ptax_quarentena_eventos").fetchone()[0],1
        )
        names=[x[0] for x in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        self.assertNotIn("nivon_snapshots",names)
        self.assertNotIn("nivon_observacoes_api",names)


if __name__=="__main__":
    unittest.main()
