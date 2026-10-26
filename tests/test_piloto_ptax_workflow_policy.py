"""Política de execução do piloto BCB: sem consultas manuais implícitas.

Verifica o contrato do workflow sem requerer PyYAML ou rede. Não prova
que GitHub Actions publicou/aprovou direitos ou implantou o terminal.
"""
import pathlib
import unittest

CAMINHO=pathlib.Path(__file__).resolve().parents[1]/".github/workflows/piloto-go-live-ptax.yml"


class TestePoliticaPilotoPTAX(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow=CAMINHO.read_text(encoding="utf-8")

    def test_dispatch_precisa_confirmacao_manual_e_main(self):
        w=self.workflow
        self.assertIn("confirmar_consulta:",w)
        self.assertIn("default: false",w)
        self.assertIn("inputs.confirmar_consulta == true",w)
        self.assertIn("github.ref == 'refs/heads/main'",w)
        self.assertIn("github.event_name == 'workflow_dispatch'",w)

    def test_ci_pr_controlada_sem_gatilho_agendado(self):
        w=self.workflow
        self.assertIn("head.ref == 'release/ptax-mainline-go-live-20261025'",w)
        self.assertIn("head.repo.full_name == 'brunocapellari-dotcom/NIVON'",w)
        self.assertNotIn("  schedule:",w)
        self.assertNotIn("  push:",w)

    def test_nem_credenciais_nem_cotacoes_nos_artefatos(self):
        w=self.workflow
        self.assertIn("persist-credentials: false",w)
        self.assertIn("permissions:\n  contents: read",w)
        self.assertNotIn("id-token: write",w)
        self.assertIn("--consultar-bcb",w)
        self.assertNotIn("--mostrar-valores",w)
        self.assertIn('"cotacao_venda" not in d',w)
        self.assertIn("retention-days: 3",w)


if __name__=="__main__":
    unittest.main()
