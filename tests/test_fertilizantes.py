import unittest
from nivon.fertilizantes import ErroFertilizantes, classificar_ncm, consolidar_importacoes


class TestFertilizantes(unittest.TestCase):
    def registro(self, **overrides):
        r={"mes":"2026-09","uf":"MT","ncm":"31021010","peso_liquido_kg":2000,
           "valor_fob_usd":700,"valor_moeda":"USD_FOB","unidade_peso":"KG"}
        r.update(overrides)
        return r

    def test_ureia_consolida_volume_e_valor_fob(self):
        x=consolidar_importacoes([self.registro(),self.registro(valor_fob_usd=800)])
        self.assertEqual(x[0]["volume_t"],4)
        self.assertEqual(x[0]["valor_unitario_fob_usd_t"],375)
        self.assertIn("NAO_CFR",x[0]["tipo_preco"])

    def test_nao_converte_fob_em_cfr(self):
        with self.assertRaises(ErroFertilizantes):
            consolidar_importacoes([self.registro(valor_moeda="USD_CFR")])

    def test_ncm_fora_de_31_nao_inclui(self):
        with self.assertRaises(ErroFertilizantes):
            consolidar_importacoes([self.registro(ncm="12019000")])

    def test_ausencia_peso_nao_cria_cotacao(self):
        x=consolidar_importacoes([self.registro(peso_liquido_kg=0)])
        self.assertIsNone(x[0]["valor_unitario_fob_usd_t"])

    def test_ncm_invalido_nao_aceita(self):
        with self.assertRaises(ErroFertilizantes):
            classificar_ncm("310210")

if __name__=="__main__":
    unittest.main()
