"""Estados de monitoramento GCP nao assumem sucesso por job verde."""
import unittest
from nivon.monitor_integridade_gcp import avaliar


def run(status="success"):
    return {"id": 1, "event": "schedule", "status": "completed",
            "conclusion": status, "created_at": "2026-10-25T08:00:00Z"}


class TestMonitorIntegridadeGCP(unittest.TestCase):
    def test_sucesso_sem_gravacao_e_classificado_como_insuficiente(self):
        a=avaliar([run()], [{"conclusion":"success",
             "steps":[{"name":"Testar contratos", "conclusion":"success"}]}])
        self.assertEqual(a["status"],"SUCESSO_SEM_ETAPA_DE_ESCRITA")
        self.assertFalse(a["persistencia_confirmada"])

    def test_job_escrita_skipped(self):
        a=avaliar([run()], [{"name":"coletar-e-persistir","conclusion":"skipped"}])
        self.assertEqual(a["status"],"PULADO_POR_GATE")

    def test_passo_gcp_skipped_em_job_verde(self):
        a=avaliar([run()], [{"conclusion":"success","steps":[
            {"name":"Credencial GCP e BigQuery","conclusion":"skipped"}]}])
        self.assertEqual(a["status"],"PULADO_POR_GATE")

    def test_passos_executados_nao_equivalem_a_readback_independente(self):
        a=avaliar([run()], [{"conclusion":"success","steps":[
            {"name":"Carregar BigQuery","conclusion":"success"},
            {"name":"Conferir BigQuery","conclusion":"success"}]}])
        self.assertEqual(a["status"],"READBACK_DECLARADO_NAO_INDEPENDENTE")
        self.assertFalse(a["persistencia_confirmada"])

    def test_sem_agenda(self):
        a=avaliar([],[])
        self.assertEqual(a["status"],"AGENDA_NAO_EXECUTADA")

    def test_falha_nao_e_encoberta(self):
        a=avaliar([run("failure")], [{"conclusion":"failure"}])
        self.assertEqual(a["status"],"FALHA")


if __name__ == "__main__":
    unittest.main()
