import unittest
from decimal import Decimal
from nivon.qualidade_cientifica import ErroCientifico
from nivon.unidades_mercado import (converter_massa,referencia_bolsa_cbot_usd_t,
    referencia_ice_centavos_libra_usd_t,fracao_de_percentual)


class TestUnidadesMercado(unittest.TestCase):
    def test_tonelada_libra_tonelada(self):
        lb=Decimal(converter_massa(valor="1",unidade_origem="T",unidade_destino="LB")["valor_decimal"])
        t=Decimal(converter_massa(valor=lb,unidade_origem="LB",unidade_destino="T")["valor_decimal"])
        self.assertAlmostEqual(float(t),1,places=12)

    def test_soja_milho_pesos_especificos_diferentes(self):
        soja=referencia_bolsa_cbot_usd_t(produto="SOJA",centavos_usd_por_bushel="1263")
        milho=referencia_bolsa_cbot_usd_t(produto="MILHO",centavos_usd_por_bushel="1263")
        self.assertEqual(soja["massa_kg_bushel"],str(Decimal("60")*Decimal(".45359237")))
        self.assertGreater(Decimal(milho["referencia_usd_t"]),Decimal(soja["referencia_usd_t"]))
        self.assertEqual(soja["preco_usd_bushel"],"12.63")

    def test_sem_bushel_generico_porque_depende_do_produto(self):
        with self.assertRaises(ErroCientifico):
            referencia_bolsa_cbot_usd_t(produto="GERGELIM",centavos_usd_por_bushel="100")

    def test_libra_centavos_para_usd_t_ice(self):
        x=referencia_ice_centavos_libra_usd_t(produto="ACUCAR",centavos_usd_por_libra="20")
        esperado=Decimal(".2")*Decimal("1000")/Decimal(".45359237")
        self.assertAlmostEqual(float(Decimal(x["referencia_usd_t"])),float(esperado))
        self.assertIn("SEM_IDENTIFICACAO",x["status"])

    def test_percentual_fisico_e_rejeicoes(self):
        self.assertEqual(fracao_de_percentual(percentual="35"),"0.35")
        for v in ("NaN",True,"101",-1):
            with self.assertRaises(ErroCientifico):
                fracao_de_percentual(percentual=v)

    def test_massa_negativa_rejeitada(self):
        with self.assertRaises(ErroCientifico):
            converter_massa(valor="-1",unidade_origem="KG",unidade_destino="T")


if __name__=="__main__":
    unittest.main()
