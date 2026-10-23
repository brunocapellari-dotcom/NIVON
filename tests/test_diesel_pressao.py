import unittest
from datetime import date
from decimal import Decimal

from nivon.diesel_pressao import sensibilidade_diesel, ErroSensibilidadeDiesel


def calcular(**alteracoes):
    kwargs = {
        "distancia_operacional_km": Decimal("500"),
        "consumo_estimado_l_km": Decimal("0.5"),
        "carga_por_viagem_t": Decimal("40"),
        "preco_diesel_base_brl_l": Decimal("6"),
        "preco_diesel_cenario_brl_l": Decimal("6.4"),
        "distancia_validada": True,
        "fonte_preco": "ANP_REVENDA_AMOSTRAL",
        "referencia_preco": date(2026, 10, 17),
        "produto_diesel": "DIESEL_S10",
        "premissas_documentadas": True,
    }
    kwargs.update(alteracoes)
    return sensibilidade_diesel(**kwargs)


class TestSensibilidadeDiesel(unittest.TestCase):
    def test_sensibilidade_nao_e_repasse_automatico(self):
        r = calcular()
        self.assertEqual(r["litros_hipoteticos_por_viagem"], "250.0")
        self.assertEqual(Decimal(r["custo_base_combustivel_brl_t"]), Decimal("37.50"))
        self.assertEqual(Decimal(r["custo_cenario_combustivel_brl_t"]), Decimal("40.00"))
        self.assertEqual(Decimal(r["variacao_custo_combustivel_brl_t"]), Decimal("2.50"))
        self.assertEqual(r["repasse_ao_frete"], "INDETERMINADO")
        self.assertNotIn("volume_realizado", r)

    def test_bloquear_premissas_nao_comprovadas(self):
        for kwargs in (
            {"distancia_validada": False},
            {"premissas_documentadas": False},
            {"consumo_estimado_l_km": Decimal("0")},
            {"preco_diesel_base_brl_l": Decimal("NaN")},
            {"carga_por_viagem_t": Decimal("-1")},
            {"referencia_preco": "2026-10-17"},
            {"fonte_preco": ""},
            {"produto_diesel": "DIESEL_S500_S10"},
            {"distancia_operacional_km": Decimal("25000")},
            {"consumo_estimado_l_km": Decimal("6")},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ErroSensibilidadeDiesel):
                calcular(**kwargs)


if __name__ == "__main__":
    unittest.main()
