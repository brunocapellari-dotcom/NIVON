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

    def test_lote_sincroniza_estados_sem_divulgar_conteudo(self):
        from nivon.maritimo_lote import executar_lote
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"hist.sqlite"
            repo=HistoricoMaritimo(path)
            html=("<table><tr><th>Navio</th><th>Berco</th><th>Situacao</th></tr>"
                  "<tr><td>NAVIO TESTE</td><td>2</td><td>Esperado</td></tr></table>")
            executar_lote(("suape","santarem_cdp"),repo,
                coletado_em="2026-10-23T07:00:00-04:00",fornecedor_html=lambda _:html)
            repo.fechar()
            fake=FakePg()
            result=sincronizar(fake,path)
            self.assertEqual(result["execucoes_processadas"],2)
            writes=[x for x in fake.calls if "coleta_execucoes" in x[0]]
            self.assertEqual(len(writes),2)
            self.assertEqual(writes[0][1][3],"OK")
            self.assertEqual(writes[1][1][3],"QUARENTENA")
            self.assertNotIn("NAVIO TESTE", str(writes))
            with self.assertRaises(FileNotFoundError):
                sincronizar(FakePg(),Path(tmp)/"nao-existe.sqlite")

if __name__=="__main__":
    unittest.main()
