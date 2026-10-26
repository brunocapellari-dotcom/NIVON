"""Gates de deploy do snapshot: jamais liberar cron por mera existencia de API."""
import unittest
from pathlib import Path
from datetime import datetime,timezone
from scripts.atualizar_snapshot_portal_gcp import planejar, ARQUIVO_PRIVADO
from nivon.portal_interno import ErroPortal


class PortalCloudPolicy(unittest.TestCase):
    def test_gcp_contrato_e_teto(self):
        d=planejar(projeto="nivon-data",dataset="nivon_raw",bucket="nivon-data-raw-2026",
            competencia="2026-08",agora=datetime(2026,10,25,tzinfo=timezone.utc))
        self.assertEqual(d["objeto_privado"],ARQUIVO_PRIVADO)
        self.assertEqual(len(d["consulta"]["consultas_maritimas_bigquery"]),2)
        self.assertEqual(d["consulta"]["ferrovia_bigquery"]["competencia"],"2026-08")
        self.assertEqual(d["consulta"]["consultas_maritimas_bigquery"][0]["inicio"],"2026-10-01")
        for kwargs in ({"competencia":"2026-11"},{"dataset":"other"},{"bucket":"public"},
                       {"competencia":"2026-00"}):
            base=dict(projeto="nivon-data",dataset="nivon_raw",
                      bucket="nivon-data-raw-2026",competencia="2026-08",
                      agora=datetime(2026,10,25,tzinfo=timezone.utc))
            with self.subTest(k=kwargs),self.assertRaises(ErroPortal):
                planejar(**(base|kwargs))

    def test_schedule_falha_fechada(self):
        path=Path(__file__).resolve().parents[1]/".github/workflows/portal-interno-gcp.yml"
        doc=path.read_text(encoding="utf-8")
        for token in ("refs/heads/main","NIVON_PORTAL_E2E_VERIFIED",
                      "NIVON_PORTAL_GCP_READ_APPROVED","NIVON_PORTAL_GCS_WRITE_APPROVED",
                      "NIVON_ZERO_COST_BQ_APPROVED","NIVON_PORTAL_PRIVATE_BUCKET_REVIEWED",
                      "id-token: write","scripts/atualizar_snapshot_portal_gcp.py"):
            self.assertIn(token,doc)
        self.assertNotIn("allow-unauthenticated",doc)
        self.assertNotIn("gcloud services enable",doc)
        self.assertNotIn("gcloud run deploy",doc)
        self.assertNotIn("upload-artifact",doc)
        self.assertNotIn("push:\n",doc)


if __name__=="__main__":
    unittest.main()
