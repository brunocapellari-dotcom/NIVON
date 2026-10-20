"""Testes offline do runner rolling-origin, com histórico sintético."""
from datetime import date, timedelta
import unittest

from nivon.quant_core import ErroQuantitativo
from nivon.rolling_origin import executar_rolling_origin_asof

CAL = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(85)]
SHA = "f" * 64


def instante(periodo, hora=18):
    return f"{periodo}T{hora:02d}:00:00Z"


def dados(*, n=76):
    return [
        {
            "serie_id": "CBOT_SOJA_NOV26", "unidade": "USC/BU",
            "fonte_id": "FONTE_TESTE",
            "periodo": CAL[i], "valor": 100 + i,
            "publicado_em": instante(CAL[i], 16),
            "coletado_em": instante(CAL[i], 17),
            "edicao_sha256": SHA,
        } for i in range(n)
    ]


def origens():
    return {CAL[i]: instante(CAL[i]) for i in (29, 33, 38, 42, 46, 50, 54, 60)}


def rodar(modelo, *, obs=None, origins=None, horizon=2, window=20, **opts):
    args = dict(
        observacoes=dados() if obs is None else obs, calendario=CAL,
        origens_em=origens() if origins is None else origins,
        as_of_avaliacao=instante(CAL[77]),
        serie_id="CBOT_SOJA_NOV26", unidade="USC/BU",
        fonte_id="FONTE_TESTE", modelo_id="REGRA_TESTE",
        horizonte_periodos=horizon, tamanho_treino=window, modelo=modelo,
        tolerancia_absoluta=0.5,
    )
    args.update(opts)
    return executar_rolling_origin_asof(**args)


class TestRollingOrigin(unittest.TestCase):
    def test_reestimacao_por_origem_e_baseline_historico(self):
        chamadas = []

        def preditor(treino, contexto):
            chamadas.append((treino, contexto))
            self.assertEqual(len(treino), 20)
            self.assertEqual(treino[-1]["periodo"], contexto["periodo_origem"])
            self.assertEqual(set(contexto), {
                "serie_id", "unidade", "modelo_id", "periodo_origem",
                "alvo_periodo", "emitido_em", "horizonte_periodos",
            })
            self.assertNotIn("real_avaliacao", contexto)
            self.assertNotIn("real", treino[-1])
            return treino[-1]["valor"] + 2

        r = rodar(preditor)
        self.assertEqual(len(chamadas), 8)
        self.assertEqual(r["metricas"]["n_folds"], 8)
        self.assertEqual(r["metricas"]["mae"], 0.0)
        self.assertEqual(r["metricas"]["mae_baseline"], 2.0)
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["metricas"]["publicavel"])
        self.assertEqual(r["arquivo_avaliacao"][0]["alvo_periodo"], CAL[31])

    def test_vintage_corrigido_nao_vaza_para_origem_anterior(self):
        obs = dados()
        obs.append({
            "serie_id": "CBOT_SOJA_NOV26", "unidade": "USC/BU",
            "fonte_id": "FONTE_TESTE",
            "periodo": CAL[25], "valor": 900,
            "publicado_em": instante(CAL[35], 16),
            "coletado_em": instante(CAL[35], 17),
            "edicao_sha256": "e"*64,
        })
        evidencias = {}

        def preditor(treino, ctx):
            if ctx["periodo_origem"] in (CAL[29], CAL[42]):
                evidencias[ctx["periodo_origem"]] = {
                    x["periodo"]: x["valor"] for x in treino
                }
            return treino[-1]["valor"] + 2

        rodar(preditor, obs=obs)
        self.assertEqual(evidencias[CAL[29]][CAL[25]], 125)
        # A janela no fold tardio começa em 23 e inclui o dado revisado.
        self.assertEqual(evidencias[CAL[42]][CAL[25]], 900)

    def test_contexto_e_treino_imutaveis(self):
        def ataque(treino, ctx):
            with self.assertRaises(TypeError):
                ctx["real"] = 999
            with self.assertRaises(TypeError):
                treino[0]["valor"] = 999
            return treino[-1]["valor"] + 2
        rodar(ataque)

    def test_recusa_modelo_injeta_real_e_metrica(self):
        for r in ({"previsto": 200, "real": 200},
                  {"previsto": 200, "brier": 0}):
            with self.subTest(r=r), self.assertRaisesRegex(ErroQuantitativo, "autorizado"):
                rodar(lambda *_: r)

    def test_recusa_erro_fisico_ou_nao_finito(self):
        for x in (True, float("nan"), float("inf"), -1):
            with self.subTest(x=x), self.assertRaises(ErroQuantitativo):
                rodar(lambda *_: x)

    def test_probability_and_interval_scoring_only_after_prediction(self):
        def modelo(treino, ctx):
            return {
                "previsto": treino[-1]["valor"] + 2,
                "intervalo_inferior": treino[-1]["valor"] + 1,
                "intervalo_superior": treino[-1]["valor"] + 3,
                "nivel_intervalo": .9,
                "probabilidades": {"ALTA": 0.8, "BAIXA": .1, "ESTABILIDADE": .1},
            }
        r = rodar(modelo)
        self.assertEqual(r["metricas"]["cobertura_intervalo"], 1.0)
        self.assertAlmostEqual(r["metricas"]["brier_multiclasse_medio"], .02)
        self.assertFalse(r["publicavel"])

    def test_sem_treino_asof_e_origem_sem_alvo_falha(self):
        obs = dados()
        obs[20]["coletado_em"] = instante(CAL[45], 17)
        with self.assertRaises(ErroQuantitativo):
            rodar(lambda t, _: t[-1]["valor"], obs=obs)
        with self.assertRaises(ErroQuantitativo):
            rodar(lambda t, _: t[-1]["valor"],
                  origins={CAL[i]: instante(CAL[i]) for i in (75, 76, 77, 78, 79)})

    def test_horizonte_e_calendario_explicitos(self):
        origins = {CAL[i]: instante(CAL[i]) for i in (40, 43, 46, 49, 52)}
        r = rodar(lambda t, _: t[-1]["valor"] + 3,
                  origins=origins, horizon=3)
        self.assertEqual(r["n_folds"], 5)
        self.assertEqual(r["metricas"]["mae"], 0)
        with self.assertRaises(ErroQuantitativo):
            rodar(lambda t, _: t[-1]["valor"], origins=origins,
                  calendario=list(reversed(CAL)))

    def test_unidades_misturadas_recusadas(self):
        obs = dados()
        obs[20]["unidade"] = "BRL/T"
        with self.assertRaisesRegex(ErroQuantitativo, "misturadas"):
            rodar(lambda t, _: t[-1]["valor"], obs=obs)

    def test_probabilidades_incompletas_ou_intervalo_invertido(self):
        for saida in (
            {"previsto": 111, "probabilidades": {"ALTA": .8}},
            {"previsto": 111, "intervalo_inferior": 120,
             "intervalo_superior": 110, "nivel_intervalo": .95}
        ):
            with self.assertRaises(ErroQuantitativo):
                rodar(lambda *_: saida)


if __name__ == "__main__":
    unittest.main()
