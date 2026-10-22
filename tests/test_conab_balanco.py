import unittest
from nivon.conab_balanco import normalizar_balanco

PUB={"url":"https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras"}
def row(**kw):
    return dict({"produto":"soja","safra":"2026/27","unidade":"mil_ton",
        "estoque_inicial":10,"producao":100,"importacao":0,"suprimento":110,
        "consumo":70,"exportacao":30,"demanda_total":100,"estoque_final":10},**kw)
class TestBalanco(unittest.TestCase):
    def test_identidades(self):
        x=normalizar_balanco([row()],"conab",PUB)
        self.assertEqual(x[0]["alertas"],[])
        self.assertFalse(x[0]["armazenado"])
    def test_inconsistencia_e_alerta_nao_corrige_numero(self):
        x=normalizar_balanco([row(estoque_final=9)],"conab",PUB)[0]
        self.assertEqual(x["alertas"],["ESTOQUE_FINAL"])
        self.assertEqual(x["metricas"]["estoque_final"],"9")
    def test_metrica_nula_nao_se_torna_zero(self):
        x=normalizar_balanco([row(demanda_total=None)],"conab",PUB)[0]
        self.assertIsNone(x["metricas"]["demanda_total"])
    def test_fonte_nao_oficial(self):
        with self.assertRaises(ValueError):
            normalizar_balanco([row()],"ibge",PUB)
    def test_unidade_incorreta(self):
        with self.assertRaises(ValueError):
            normalizar_balanco([row(unidade="ton")],"conab",PUB)
if __name__=="__main__":
    unittest.main()
