"""Contrato de sincronizacao local -> Neon, usando conexao simulada."""
import tempfile
import unittest
from pathlib import Path
from nivon.maritimo_pipeline import HistoricoMaritimo, processar_html
from nivon.maritimo_neon import sincronizar
from nivon.portwatch_fluxos import HistoricoPortWatch, normalizar
import json

class FakeTransaction:
    def __enter__(self):return self
    def __exit__(self, *args):return False

class FakePg:
    def __init__(self):self.calls=[]
    def transaction(self):return FakeTransaction()
    def execute(self,sql,args):self.calls.append((sql,args))

class TestReplicacao(unittest.TestCase):
    def test_bancos_em_uma_transacao_sem_promover_cdp(self):
        with tempfile.TemporaryDirectory() as tmp:
            one=Path(tmp)/"portos.db"
            two=Path(tmp)/"portwatch.db"
            repo=HistoricoMaritimo(one)
            html=("<table><tr><th>Navio</th><th>Berco</th><th>Situacao</th></tr>"
                  "<tr><td>SYNTHETIC SHIP</td><td>2</td><td>Esperado</td></tr></table>")
            processar_html("santarem_cdp",html,repo,coletado_em="2026-10-22T23:00:00Z")
            repo.fechar()
            port=HistoricoPortWatch(two)
            fixture={"features":[{"attributes":{"portname":"Suez Canal","portid":"CHOKEPOINT_TEST",
               "date":"2026-10-20","n_total":10,"capacity":200,"n_dry_bulk":3,"n_tanker":5}}]}
            normalized,_=normalizar(json.dumps(fixture).encode(),
               consultadas=["suez"],coletado_em="2026-10-22T23:00:00Z")
            port.inserir(normalized)
            port.fechar()
            fake=FakePg()
            result=sincronizar(fake,one,banco_portwatch=two)
            self.assertEqual(result,{"capturas_processadas":1,"revisoes_processadas":1,"passagens_processadas":1})
            self.assertEqual(len(fake.calls),3)
            self.assertIn("ON CONFLICT",fake.calls[0][0])
            self.assertFalse(fake.calls[1][1][6])
            self.assertEqual(fake.calls[2][1][5],10)
            self.assertEqual(fake.calls[2][1][6],200)

if __name__=="__main__":
    unittest.main()
