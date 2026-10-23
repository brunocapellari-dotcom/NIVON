import unittest

from nivon.motores import DadoInvalido
from nivon.pecuaria_ciclos import (
    custo_racao_kg, simular_ciclo_bovino, simular_lote_frango, simular_lote_suino,
)

FONTE = "hipotese sintetica identificada; nao dado real"


class TestPecuariaCiclos(unittest.TestCase):
    def _racao(self):
        return dict(fracao_milho=.65, fracao_farelo_soja=.30, fracao_outros=.05,
                    preco_milho_rs_t=1000, preco_farelo_soja_rs_t=2000,
                    preco_outros_rs_t=500, fonte_parametros=FONTE)

    def test_racao_em_rs_kg_e_nao_rs_t(self):
        self.assertAlmostEqual(custo_racao_kg(**self._racao()), 1.275)

    def test_racao_sem_balanco_rejeitada(self):
        with self.assertRaises(DadoInvalido):
            custo_racao_kg(**dict(self._racao(), fracao_milho=.5))

    def test_racao_nao_admite_preco_negativo_nan_bool(self):
        for preco in (True, -1, float("nan"), float("inf")):
            with self.assertRaises(DadoInvalido):
                custo_racao_kg(**dict(self._racao(), preco_milho_rs_t=preco))

    def test_bovino_arroba_carcaca_e_margem_por_cabeca(self):
        x = simular_ciclo_bovino(
            peso_vivo_saida_kg=500, rendimento_carcaca=.52,
            preco_boi_rs_arroba_carcaca=300, preco_reposicao_rs_cabeca=2000,
            dias_engorda=100, consumo_racao_kg_dia=5, custo_racao_rs_kg=1,
            outros_custos_rs_cabeca=500, fonte_parametros=FONTE)
        self.assertAlmostEqual(x["arrobas_carcaca_cabeca"], 260/15)
        self.assertAlmostEqual(x["receita_bruta_rs_cabeca"], 5200)
        self.assertAlmostEqual(x["margem_declarada_rs_cabeca"], 2200)
        self.assertFalse(x["homologado"])

    def test_bovino_rendimento_e_dias_invalidos(self):
        arg = dict(peso_vivo_saida_kg=500, rendimento_carcaca=.52,
                   preco_boi_rs_arroba_carcaca=300, preco_reposicao_rs_cabeca=1000,
                   dias_engorda=100, consumo_racao_kg_dia=2, custo_racao_rs_kg=1,
                   outros_custos_rs_cabeca=10, fonte_parametros=FONTE)
        for bad in (dict(rendimento_carcaca=1.01), dict(rendimento_carcaca=0),
                    dict(dias_engorda=1.5), dict(preco_boi_rs_arroba_carcaca=True)):
            with self.assertRaises(DadoInvalido):
                simular_ciclo_bovino(**dict(arg, **bad))

    def test_frango_sobrevivencia_receita_e_custo_lote(self):
        x = simular_lote_frango(aves_alojadas=100, mortalidade_fracao=.1,
            peso_vivo_saida_kg_ave=2.5, preco_frango_vivo_rs_kg=6,
            racao_kg_por_ave_alojada=4, custo_racao_rs_kg=1.25,
            custo_pintinho_rs_ave_alojada=2, outros_custos_rs_ave_alojada=1,
            fonte_parametros=FONTE)
        self.assertAlmostEqual(x["receita_bruta_rs_lote"], 1350)
        self.assertAlmostEqual(x["custo_declarado_rs_lote"], 800)
        self.assertAlmostEqual(x["margem_declarada_rs_lote"], 550)
        self.assertEqual(x["cadeia"], "FRANGO")

    def test_suino_terminacao_sem_confundir_rebanho(self):
        x = simular_lote_suino(suinos_entrada=10, mortalidade_fracao=0,
            peso_vivo_saida_kg_suino=120, preco_suino_vivo_rs_kg=8,
            racao_kg_por_suino_entrada=250, custo_racao_rs_kg=1.4,
            aquisicao_rs_suino_entrada=300, outros_custos_rs_suino_entrada=150,
            fonte_parametros=FONTE)
        self.assertAlmostEqual(x["receita_bruta_rs_lote"], 9600)
        self.assertAlmostEqual(x["custo_declarado_rs_lote"], 8000)
        self.assertAlmostEqual(x["margem_declarada_rs_lote"], 1600)
        self.assertEqual(x["cadeia"], "SUINO")

    def test_lotes_bloqueiam_contagens_e_mortalidade_invalidas(self):
        args = dict(suinos_entrada=10, mortalidade_fracao=.2,
            peso_vivo_saida_kg_suino=120, preco_suino_vivo_rs_kg=8,
            racao_kg_por_suino_entrada=250, custo_racao_rs_kg=1.4,
            aquisicao_rs_suino_entrada=300, outros_custos_rs_suino_entrada=150,
            fonte_parametros=FONTE)
        for bad in (dict(suinos_entrada=2.5), dict(suinos_entrada=True),
                    dict(mortalidade_fracao=1), dict(mortalidade_fracao=-.01)):
            with self.assertRaises(DadoInvalido):
                simular_lote_suino(**dict(args, **bad))


if __name__ == "__main__":
    unittest.main()
