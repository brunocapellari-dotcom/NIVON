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


    def test_gpv_importa_arquivo_autorizado_no_historico(self):
        from nivon.maritimo_pipeline import processar_gpv
        repo=HistoricoMaritimo()
        csv_content="Navio,IMO,Status,BERÇO,Produto,Toneladas\nNAVIO SIMULADO,1234567,Esperado,1,Minério,1200"
        result=processar_gpv(csv_content,repo,acesso_autorizado=True,coletado_em=NOW)
        self.assertEqual(result["revisoes_novas"],1)
        self.assertEqual(len(repo.atuais("ponta_madeira")),1)
        with self.assertRaises(PermissionError):
            processar_gpv(csv_content,repo,acesso_autorizado=False,coletado_em=NOW)
        repo.fechar()

    def test_ais_nivon_mmsi_sem_imo_e_geocerca(self):
        from nivon.maritimo_pipeline import normalizar_eventos_ais_nivon
        events=[{"MessageType":"PositionReport",
            "MetaData":{"MMSI":123456789,"Latitude":0.5,"Longitude":0.5},
            "Message":{"PositionReport":{"UserID":123456789,"Valid":True}},
            "recebido_em":f"2026-10-22T{hour:02d}:00:00Z"}
            for hour in (12,13,14)]
        normalized=normalizar_eventos_ais_nivon(events)
        self.assertEqual(len(normalized),3)
        self.assertIsNone(normalized[0].get("imo"))
        repo=HistoricoMaritimo()
        output=processar_ais_amaggi(normalized,repo,geocerca_auditada=[(0,0),(0,1),(1,1),(1,0)],coletado_em=NOW)
        self.assertEqual(output["registros"],1)
        self.assertEqual(repo.contagens()["revisoes"],1)
        self.assertEqual(repo.contagens()["atuais"],0)
        repo.fechar()

    def test_stream_ais_nivon_integrado_sem_conversor_manual(self):
        from nivon.maritimo_pipeline import normalizar_eventos_ais_nivon
        from nivon.maritime.ais_stream import parse_aisstream_message
        collected=[]
        for h in (11,12,13):
            frame={"MetaData":{"MMSI":123456789,"latitude":0.25,"longitude":0.25,
                    "time_utc":f"2026-10-22T{h:02d}:00:00Z"},
                   "MessageType":"PositionReport",
                   "Message":{"PositionReport":{"UserID":123456789}}}
            collected.append(parse_aisstream_message(frame,received_at="2026-10-22T13:01:00Z"))
        positions=normalizar_eventos_ais_nivon(collected)
        self.assertEqual(len(positions),3)
        self.assertEqual(positions[0]["mmsi"],"123456789")
        repo=HistoricoMaritimo()
        outcome=processar_ais_amaggi(positions,repo,
          geocerca_auditada=[(0,0),(0,1),(1,1),(1,0)],coletado_em=NOW)
        self.assertEqual(outcome["registros"],1)
        self.assertEqual(repo.contagens()["atuais"],0)
        repo.fechar()

if __name__ == "__main__":
    unittest.main()
