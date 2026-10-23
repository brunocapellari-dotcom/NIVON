import unittest
from types import SimpleNamespace
from datetime import datetime
from nivon.imea_lotes import prepare,verify_meta

META=SimpleNamespace(source="imea",source_url="https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes")
def record(i,**extra):
    r={"cadeia":"soja","indicador_id":str(i),"indicador":"Preço soja disponível",
       "localidade":"Sorriso","unidade":"R$/sc","valor":150.5,
       "safra":"26/27","data_publicacao":datetime(2026,10,21,13,0)}
    r.update(extra)
    return r

class TestLotesIMEA(unittest.TestCase):
    def test_lotes_paginados_completo(self):
        x=prepare([record(i) for i in range(201)],META,"soja",batch_size=80)
        self.assertEqual([len(b) for b in x["batches"]],[80,80,41])
        self.assertEqual(x["validated"],201)
        self.assertEqual(x["reference_dates_verified"],0)
        self.assertEqual(x["state"],"STAGING_ONLY")
        self.assertTrue(all(r["reference_date"] is None for batch in x["batches"] for r in batch))
    def test_quarentena_duplicatas_e_zero(self):
        x=prepare([record(1),record(1),record(2,valor=0),record(3)],META,"soja")
        self.assertEqual(x["validated"],2)
        self.assertEqual(x["discarded"],2)
        self.assertIn("DUPLICATA_EXATA_NA_COLETA",x["discard_reasons"])
    def test_metadata_rejeita_fonte_alterna(self):
        for m in (
            SimpleNamespace(source="noticias_agricolas",source_url=META.source_url),
            SimpleNamespace(source="imea",source_url="https://api1.imea.com.br.evil.test/api/v2/mobile/cadeias/4/cotacoes"),
            SimpleNamespace(source="imea",source_url="http://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes"),
            SimpleNamespace(source="imea",source_url="https://api1.imea.com.br/api/v2/mobile/cadeias/3/cotacoes"),
        ):
            with self.subTest(m=m),self.assertRaises(ValueError):
                verify_meta(m,"soja")
    def test_recusa_cross_chain(self):
        with self.assertRaises(ValueError):
            prepare([record(1,cadeia="milho")],META,"soja")
    def test_fallback_sem_preco_rejeitado(self):
        with self.assertRaises(ValueError):
            prepare([record(1,indicador="Semente de soja")],META,"soja")
    def test_limitacao_tamanho(self):
        for n in (0,101,True):
            with self.subTest(n=n),self.assertRaises(ValueError):
                prepare([record(1)],META,"soja",batch_size=n)
if __name__=="__main__":
    unittest.main()
