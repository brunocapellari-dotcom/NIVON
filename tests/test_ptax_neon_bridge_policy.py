"""A ponte PTAX legado não pode expor token/dados nem rodar em PR."""
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
import unittest

from scripts import ptax_neon_private_export as bridge

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/ptax-neon-private-export.yml"


class TestPTAXBridgeSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.yaml=WORKFLOW.read_text(encoding="utf-8")
        cls.offline=cls.yaml.split("  validar:",1)[1].split("  exportar-e-sincronizar:",1)[0]
        cls.work=cls.yaml.split("  exportar-e-sincronizar:",1)[1]
        cls.gate=cls.work.split("    runs-on:",1)[0]

    def test_ci_push_pr_sem_token_ou_neon(self):
        self.assertIn("  push:", self.yaml)
        self.assertIn("  pull_request:", self.yaml)
        self.assertIn("  schedule:", self.yaml)
        self.assertIn("  workflow_dispatch:", self.yaml)
        self.assertIn("    needs: validar", self.work)
        self.assertNotIn("id-token: write",self.offline)
        self.assertNotIn("google-github-actions/auth",self.offline)
        self.assertNotIn("NIVON_PTAX_PRIVATE_ENDPOINT",self.offline)
        self.assertIn("      id-token: write",self.work)

    def test_exportacao_somente_agendada_ou_manual_na_main(self):
        self.assertIn("github.ref == 'refs/heads/main'",self.gate)
        self.assertIn("github.event_name == 'schedule'",self.gate)
        self.assertIn("github.event_name == 'workflow_dispatch'",self.gate)
        self.assertNotIn("github.event_name == 'push'",self.gate)
        self.assertNotIn("github.event_name != 'pull_request'",self.gate)
        self.assertNotIn("31ce2bd7b83f1356efa15159a55e564125eb7b95",self.work)
        self.assertIn("NIVON_GCP_WRITE_APPROVED == 'true'",self.work)
        self.assertIn("NIVON_GCP_COST_REVIEWED == 'true'",self.work)
        self.assertIn("NIVON_PTAX_DIRECT_WRITER_APPROVED != 'true'",self.work)
        self.assertIn("group: nivon-ptax-neon-bigquery",self.yaml)

    def test_falha_http_expoe_somente_codigo_numerico(self):
        saida=StringIO()
        erro=HTTPError("https://segredo.example/ponte?token=TOPSECRET",403,
                       "access denied: contains private token",None,None)
        with patch.object(bridge,"token_from_actions",return_value="token_teste"),\
             patch.object(bridge,"export",side_effect=erro),redirect_stderr(saida):
            code=bridge.main(["--endpoint","https://host.example",
                "--source-jsonl","/tmp/teste-ptax-origem.jsonl",
                "--target-jsonl","/tmp/teste-ptax-destino.jsonl"])
        self.assertEqual(code,3)
        self.assertIn("HTTP_403:NO_CLOUD_WRITE",saida.getvalue())
        self.assertNotIn("TOPSECRET",saida.getvalue())
        self.assertNotIn("segredo.example",saida.getvalue())
        self.assertNotIn("access denied",saida.getvalue())

    def test_sem_http_nao_finge_sucesso_com_dados_falsos(self):
        self.assertEqual(bridge.MAX_ROWS,100_000)
        self.assertEqual(bridge.AUDIENCE,"urn:nivon:ptax:export:v1")


if __name__=="__main__":
    unittest.main()
