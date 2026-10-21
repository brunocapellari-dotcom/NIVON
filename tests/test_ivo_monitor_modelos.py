import unittest

from nivon.ivo_monitor_modelos import diagnosticar_performance
from nivon.ivo_previsao_ledger import ErroLedger


def relatorio(erros, *, coberturas=None):
    return {
        "status": "AVALIACAO_DESCRITIVA_NAO_HOMOLOGADA",
        "agregacao_comparavel": True, "modo": "BACKTEST",
        "verdade": "PRIMEIRA_PUBLICACAO",
        "avaliacoes": [
            {
                "periodo": f"2025-{i+1:02d}",
                "erro_absoluto": e,
                "erro_baseline": 5.,
                "dentro_intervalo": None if coberturas is None else coberturas[i],
            }
            for i, e in enumerate(erros)
        ],
    }


class TestIVOMonitor(unittest.TestCase):
    def test_degradacao_dispara_alerta_sem_retreinar(self):
        r = diagnosticar_performance(relatorio([2.]*6 + [6.]*3))
        self.assertEqual(r["status"], "ALERTA_DESEMPENHO")
        self.assertTrue(r["sugere_reavaliacao"])
        self.assertFalse(r["retreino_automatico"])
        self.assertFalse(r["promocao_automatica"])
        self.assertEqual(r["fator_erro_recente"], 3.)

    def test_estavel_nao_dispara(self):
        r = diagnosticar_performance(relatorio([2.]*9))
        self.assertEqual(r["status"], "SEM_ALERTA_NESTA_JANELA")
        self.assertFalse(r["sugere_reavaliacao"])

    def test_cobertura_baixa_dispara_mesmo_com_mae_baixo(self):
        r = diagnosticar_performance(relatorio([2.]*9, coberturas=[True]*6+[False]*3))
        self.assertTrue(r["cobertura_baixa"])
        self.assertEqual(r["cobertura_recente"], 0.)
        self.assertEqual(r["status"], "ALERTA_DESEMPENHO")

    def test_intervalo_ausente_nao_virar_cobertura_zero(self):
        r = diagnosticar_performance(relatorio([2.]*9))
        self.assertIsNone(r["cobertura_recente"])
        self.assertFalse(r["cobertura_baixa"])

    def test_erro_historico_zero(self):
        r = diagnosticar_performance(relatorio([0.]*6+[1.]*3))
        self.assertTrue(r["historico_erro_zero_e_novo_erro"])
        self.assertIsNone(r["fator_erro_recente"])

    def test_quantidade_insuficiente(self):
        r = diagnosticar_performance(relatorio([1.]*7))
        self.assertEqual(r["status"], "HISTORICO_INSUFICIENTE")
        self.assertFalse(r["sugere_reavaliacao"])

    def test_bloqueia_relatorio_nao_comparavel(self):
        a = relatorio([1.]*9)
        a["status"] = "BLOQUEADO_AGREGACAO_ESCOPOS_DIFERENTES"
        with self.assertRaises(ErroLedger):
            diagnosticar_performance(a)

    def test_bloqueia_duplicacoes_periodo(self):
        a = relatorio([1.]*9)
        a["avaliacoes"][-1]["periodo"] = a["avaliacoes"][0]["periodo"]
        with self.assertRaises(ErroLedger):
            diagnosticar_performance(a)

    def test_limites_invalidos(self):
        for opts in ({"minimo_historico": 2}, {"janela_recente": 1},
                     {"fator_alerta": 1.0}, {"cobertura_minima": 0},
                     {"fator_alerta": float("inf")}):
            with self.subTest(opts=opts):
                with self.assertRaises(ErroLedger):
                    diagnosticar_performance(relatorio([1.]*10), **opts)


if __name__ == "__main__":
    unittest.main()
