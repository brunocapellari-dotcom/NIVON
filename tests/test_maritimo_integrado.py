"""Testes de integracao de captura, persistencia, revisao, quarentena e AIS."""
import json
import tempfile
import unittest
from pathlib import Path
from nivon.maritimo_pipeline import (
    HistoricoMaritimo, processar_html, processar_ais_amaggi,
    baixar_html, ColetaMaritimaErro
)

NOW = "2026-10-22T23:20:00Z"
def html(status="Esperado", navio="NAVIO SINTETICO"):
    return ("<h3>Programacao</h3><table><tr><th>Navio</th><th>IMO</th>"
            "<th>Situacao</th><th>Berco</th><th>Carga</th><th>Toneladas</th>"
            "<th>Chegada</th></tr><tr><td>"+navio+"</td><td>1234567</td><td>"
            +status+"</td><td>2</td><td>Soja</td><td>1000</td><td>22/10/2026"
            "</td></tr></table>")

class IntegracaoMaritima(unittest.TestCase):
    def test_fluxo_completo_e_historico_persistente(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"historico.sqlite"
            repo = HistoricoMaritimo(path)
            first = processar_html("suape", html(), repo, coletado_em=NOW)
            second = processar_html("suape", html(), repo, coletado_em=NOW)
            self.assertEqual(first["revisoes_novas"], 1)
            self.assertEqual(second["revisoes_novas"], 0)
            self.assertEqual(repo.contagens(), {"capturas": 1, "revisoes": 1, "atuais": 1})
            modified = processar_html("suape", html("Atracado"), repo, coletado_em="2026-10-22T23:40:00Z")
            self.assertEqual(modified["revisoes_novas"], 1)
            self.assertEqual(repo.contagens()["revisoes"], 2)
            self.assertEqual(repo.atuais("suape")[0]["status"], "ATRACADO_INFORMADO")
            self.assertFalse(repo.atuais("suape")[0]["realizado_confirmado"])
            repo.fechar()
            again = HistoricoMaritimo(path)
            self.assertEqual(again.contagens()["revisoes"], 2)
            self.assertEqual(len(again.atuais("suape")), 1)
            again.fechar()

    def test_cdp_em_quarentena(self):
        repo = HistoricoMaritimo()
        result = processar_html("santarem_cdp", html(), repo, coletado_em=NOW)
        self.assertTrue(result["qualidade"]["quarentena"])
        self.assertEqual(repo.contagens()["revisoes"], 1)
        self.assertEqual(repo.contagens()["atuais"], 0)
        self.assertIn("RECONCILIACAO_INDEPENDENTE_PENDENTE", result["qualidade"]["flags"])
        repo.fechar()

    def test_html_invalido_nao_apaga_base(self):
        repo = HistoricoMaritimo()
        processar_html("imbituba", html(), repo, coletado_em=NOW)
        result = processar_html("imbituba", "<h3>sem tabela</h3>", repo, coletado_em=NOW)
        self.assertTrue(result["qualidade"]["quarentena"])
        self.assertEqual(len(repo.atuais("imbituba")), 1)
        repo.fechar()

    def test_ais_multiplas_visitas_nao_confirmam_embarque(self):
        repo = HistoricoMaritimo()
        polygon = [(0,0),(0,1),(1,1),(1,0)]
        points = [
            {"imo":"1234567","latitude":0.5,"longitude":0.5,
             "timestamp":f"2026-10-{day:02d}T{hour:02d}:00:00Z"}
            for day in (20,22) for hour in (12,13,14)
        ]
        summary = processar_ais_amaggi(points, repo, geocerca_auditada=polygon, coletado_em=NOW)
        self.assertEqual(summary["registros"], 2)
        self.assertEqual(repo.contagens()["atuais"], 0)
        self.assertEqual(repo.contagens()["revisoes"], 2)
        self.assertEqual(summary["qualidade"]["flags"], ["SOMENTE_INFERENCIA_AIS"])
        repo.fechar()

    def test_rede_nao_habilitada_e_gpv_fora_de_html(self):
        with self.assertRaises(PermissionError):
            baixar_html("suape")
        with self.assertRaises(ColetaMaritimaErro):
            baixar_html("ponta_madeira", habilitar_rede=True)

if __name__ == "__main__":
    unittest.main()
