"""Batch E2E, isolamento por fonte, quarentena CDP, PortWatch e replicas Neon."""
import json
import tempfile
import unittest
from pathlib import Path

from nivon.maritimo_pipeline import HistoricoMaritimo
from nivon.maritimo_lote import executar_lote, executar_portwatch

NOW="2026-10-23T07:00:00-04:00"
HTML=("<h3>Programacao</h3><table><tr><th>Navio</th><th>Berco</th>"
      "<th>Situacao</th><th>Chegada</th></tr><tr><td>TEST VESSEL</td>"
      "<td>2</td><td>Esperado</td><td>23/10/2026</td></tr></table>")

class LoteOperacional(unittest.TestCase):
    def test_multipla_fonte_falha_isolada_e_replay_idempotente(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"hist.sqlite"
            db=HistoricoMaritimo(p)
            def provider(f):
                if f=="imbituba": raise OSError("rede redigida com url e credencial")
                return HTML
            first=executar_lote(("suape","imbituba","santarem_cdp","vila_conde_cdp"),
                  db,coletado_em=NOW,fornecedor_html=provider)
            self.assertEqual(first["estados"],{"OK":1,"QUARENTENA":2,"FALHA":1})
            self.assertEqual(first["fontes"][1]["motivo"],"TRANSPORTE_INDISPONIVEL")
            self.assertNotIn("credencial",json.dumps(first))
            self.assertEqual(db.contagens()["capturas"],3)
            self.assertEqual(db.contagens()["revisoes"],3)
            self.assertEqual(len(db.atuais()),1)
            second=executar_lote(("suape","imbituba","santarem_cdp","vila_conde_cdp"),
                  db,coletado_em=NOW,fornecedor_html=provider)
            self.assertEqual(second["fontes"][0]["revisoes"],0)
            self.assertEqual(db.con.execute("SELECT COUNT(*) FROM lote_execucoes").fetchone()[0],8)
            db.fechar()
            reopened=HistoricoMaritimo(p)
            self.assertEqual(reopened.contagens()["capturas"],3)
            self.assertEqual(reopened.con.execute("SELECT COUNT(*) FROM lote_execucoes").fetchone()[0],8)
            reopened.fechar()

    def test_quarentena_nao_promove_registro_antigo(self):
        db=HistoricoMaritimo()
        result=executar_lote(("suape",),db,coletado_em=NOW,
                             fornecedor_html=lambda _: "<html><body>sem navios</body></html>")
        self.assertEqual(result["estados"]["QUARENTENA"],1)
        self.assertFalse(result["apto_operacao"])
        self.assertEqual(db.contagens()["atuais"],0)
        db.fechar()

    def test_invalidacao_lista_e_sem_rede_implicitamente(self):
        db=HistoricoMaritimo()
        with self.assertRaises(ValueError):
            executar_lote(("suape","suape"),db,fornecedor_html=lambda _:HTML)
        with self.assertRaises(PermissionError):
            executar_lote(("suape",),db)
        db.fechar()

    def test_portwatch_snapshot_armazenado_sem_carga_realizada(self):
        with tempfile.TemporaryDirectory() as d:
            db=HistoricoMaritimo(Path(d)/"hist.sqlite")
            out=Path(d)/"portwatch.sqlite"
            raw=json.dumps({"features":[{"attributes":{
                "portname":"Suez Canal","portid":"CHOKEPOINT7",
                "date":"2026-10-19","n_total":12,"n_dry_bulk":4,"n_tanker":5,
                "capacity":96000}}]}).encode()
            result=executar_portwatch(("suez",),"2026-10-19","2026-10-19",
                 banco_lineups=db,banco_portwatch=out,coletado_em=NOW,fornecer_json=raw)
            self.assertEqual(result["estado"],"OK")
            self.assertEqual(result["quantidade"],1)
            self.assertEqual(db.con.execute("SELECT count(*) FROM lote_execucoes").fetchone()[0],1)
            self.assertTrue(out.exists())
            db.fechar()

if __name__=="__main__":
    unittest.main()
