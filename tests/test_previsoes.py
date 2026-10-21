import unittest

from nivon.previsoes import ErroValidacao, avaliar_crescimento_anual


class TestPrevisoesAnuais(unittest.TestCase):
    def crescente(self):
        return {2020 + i: 100 * 1.05 ** i for i in range(8)}

    def test_crescimento_exato_cagr_recupera_tendencia(self):
        r = avaliar_crescimento_anual(self.crescente())
        self.assertEqual(r["quantidade_folds"], 4)
        self.assertTrue(r["melhora_sobre_baseline"])
        self.assertLess(r["mae_cagr"], 1e-9)
        self.assertFalse(r["pode_promover_modelo"])

    def test_folds_nunca_usam_ano_previsto_para_treino(self):
        r = avaliar_crescimento_anual(self.crescente())
        self.assertTrue(all(x["ano_treino_ate"] + 1 == x["ano_previsto"]
                            for x in r["folds"]))

    def test_estavel_baseline_nao_e_pior(self):
        s = {2020 + i: 100.0 for i in range(8)}
        r = avaliar_crescimento_anual(s)
        self.assertFalse(r["melhora_sobre_baseline"])
        self.assertEqual(r["mae_baseline"], 0)

    def test_falta_historia_erro(self):
        with self.assertRaises(ErroValidacao):
            avaliar_crescimento_anual({2020: 1, 2021: 2, 2022: 3, 2023: 4, 2024: 5})

    def test_lacuna_entre_anos_rejeitada(self):
        s = self.crescente()
        del s[2024]
        with self.assertRaises(ErroValidacao):
            avaliar_crescimento_anual(s)

    def test_nulo_ou_negativo_rejeitado(self):
        s = self.crescente()
        s[2022] = None
        with self.assertRaises(ErroValidacao):
            avaliar_crescimento_anual(s)
        s[2022] = -1
        with self.assertRaises(ErroValidacao):
            avaliar_crescimento_anual(s)

    def test_janela_de_5_anos(self):
        s = {2015 + i: 100 + i * 2 for i in range(10)}
        r = avaliar_crescimento_anual(s, janela=5)
        self.assertEqual(r["quantidade_folds"], 4)

    def test_proibido_promover_sem_vintages(self):
        r = avaliar_crescimento_anual(self.crescente())
        self.assertFalse(r["pode_promover_modelo"])
        self.assertIn("vintages", r["motivo_gate"])


if __name__ == "__main__":
    unittest.main()
