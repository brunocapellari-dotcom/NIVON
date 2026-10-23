import unittest
from nivon.qualidade_cientifica import (
    ErroCientifico, identidade_safra, balanco_massa, auditar_backtest_temporal,
)


def folds(lag=False):
    return [
        {"emitido_em": f"2026-01-{i+1:02d}T12:00:00-04:00",
         "disponivel_ate": f"2025-12-{20+i:02d}T12:00:00-04:00",
         "baseline_disponivel_em": f"2025-12-{20+i:02d}T12:00:00-04:00",
         "observado_em": f"2026-02-{i+1:02d}T12:00:00-04:00",
         "real": 100+i, "previsto": 100+i+0.2, "baseline": 103+i}
        for i in range(5)
    ]


class TestQualidadeCientifica(unittest.TestCase):
    def test_area_produtividade_producao_conservam(self):
        r = identidade_safra(
            area_colhida_ha=100, produtividade_kg_ha=3500,
            producao_reportada_t=350, resolucao_area_ha=1,
            resolucao_produtividade_kg_ha=1, resolucao_producao_t=1,
        )
        self.assertTrue(r["consistente"])
        self.assertEqual(r["producao_calculada_t"], 350)

    def test_area_produtividade_incoerente_reprovada(self):
        r = identidade_safra(
            area_colhida_ha=100, produtividade_kg_ha=3500,
            producao_reportada_t=450, resolucao_area_ha=1,
            resolucao_produtividade_kg_ha=1, resolucao_producao_t=1,
        )
        self.assertFalse(r["consistente"])

    def test_balanceamento_nao_esconde_erro(self):
        x = balanco_massa(estoque_inicial_t=10,producao_t=100,importacao_t=0,
            consumo_t=50,exportacao_t=40,perdas_t=5,estoque_final_t=15)
        self.assertTrue(x["consistente"])
        y = balanco_massa(estoque_inicial_t=10,producao_t=100,importacao_t=0,
            consumo_t=50,exportacao_t=40,perdas_t=5,estoque_final_t=5)
        self.assertFalse(y["consistente"])
        self.assertEqual(y["residuo_nao_explicado_t"],10)

    def test_numero_invalido_rejeitado(self):
        with self.assertRaises(ErroCientifico):
            identidade_safra(area_colhida_ha=True,produtividade_kg_ha=3500,
                producao_reportada_t=350,resolucao_area_ha=1,
                resolucao_produtividade_kg_ha=1,resolucao_producao_t=1)

    def test_backtest_sem_lookahead(self):
        r = auditar_backtest_temporal(folds())
        self.assertTrue(r["melhor_mae_e_rmse"])
        self.assertFalse(r["autoriza_publicacao_preditiva"])

    def test_backtest_leakage_rejeitado(self):
        f = folds()
        f[0]["disponivel_ate"] = "2026-02-08T12:00:00-04:00"
        with self.assertRaisesRegex(ErroCientifico, "vazamento"):
            auditar_backtest_temporal(f)

    def test_baseline_futuro_rejeitado(self):
        f = folds()
        f[0]["baseline_disponivel_em"] = "2026-02-08T12:00:00-04:00"
        with self.assertRaises(ErroCientifico):
            auditar_backtest_temporal(f)

    def test_folds_insuficientes_rejeitados(self):
        with self.assertRaises(ErroCientifico):
            auditar_backtest_temporal(folds()[:4])

    def test_previsao_pior_nao_ganha(self):
        f = folds()
        for row in f:
            row["previsto"] = row["real"] + 20
        self.assertFalse(auditar_backtest_temporal(f)["melhor_mae_e_rmse"])

    def test_timestamp_sem_fuso_bloqueado(self):
        f = folds()
        f[0]["emitido_em"] = "2026-01-01T12:00:00"
        with self.assertRaises(ErroCientifico):
            auditar_backtest_temporal(f)


if __name__ == "__main__":
    unittest.main()
