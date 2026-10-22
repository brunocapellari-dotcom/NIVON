"""Regressao offline: novas fontes em rotas e direitos ainda bloqueados."""
import unittest
from nivon.catalogo_fontes import carregar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas

class TestColetoresNovosNoCatalogo(unittest.TestCase):
    def test_sem_duplicacao_e_sem_coleta_produtiva(self):
        c=carregar_catalogo()
        r=carregar_rotas()
        report=validar_rotas(r,c)
        self.assertEqual(report["datasets"],report["rotas"])
        ids=["CEPEA_FISICO","IMEA_FISICO","INMET_CATALOGO_ESTACOES",
             "CPTEC_PREVISAO_CIDADE","CEMADEN_CHUVA_ACUMULADA_RECENTE"]
        d={x["id"]:x for x in c["datasets"]}
        rotas={x["dataset_id"]:x for x in r["entries"]}
        for id_ in ids:
            with self.subTest(dataset=id_):
                self.assertIn(id_,d)
                self.assertFalse(d[id_]["enabled"])
                self.assertFalse(d[id_]["collection_authorized"])
                self.assertFalse(d[id_]["commercial_redistribution_authorized"])
                self.assertFalse(rotas[id_]["runtime_enabled"])
                self.assertFalse(rotas[id_]["scheduled_enabled"])
                self.assertIsNone(rotas[id_]["last_verified_data"])
        for id_ in ("CEPEA_FISICO","IMEA_FISICO"):
            self.assertEqual(d[id_]["stage"],"BLOCKED_RIGHTS")
            self.assertEqual(rotas[id_]["collector_class"],"ACCESS_GATED")
            self.assertIn("RIGHTS_COLLECTION",rotas[id_]["gates_missing"])
            self.assertEqual(d[id_]["existing_module"],"importacao_cotacoes_autorizadas.py")
        self.assertEqual(d["CEMADEN_CHUVA_ACUMULADA_RECENTE"]["stage"],"BLOCKED_RIGHTS")

if __name__ == "__main__":
    unittest.main()
