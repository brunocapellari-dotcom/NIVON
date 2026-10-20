"""Regressoes do contrato quantitativo comum; somente fixtures sinteticas."""
import unittest
from datetime import date, datetime, timedelta, timezone

from nivon.quant_core import (
    ErroQuantitativo, avaliar_previsoes_oos, preparar_folds_asof,
    tendencia_empirica_oos,
)

SHA = "a" * 64
CAL = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(110)]


def instant(d, hour=18):
    return d + f"T{hour:02d}:00:00+00:00"


def arquivo(n=35, model="MOD1", neg=False):
    rows = []
    for i in range(10, 10+n):
        origem, alvo = CAL[i], CAL[i+1]
        v = 100 + (i % 5)
        p = v + (2 if i%3 else -1)
        r = p + (1 if i % 2 else -1)
        rows.append({
            "serie_id": "CBOT_SOJA_NOV26", "modelo_id": model, "unidade": "USC/BU",
            "baseline_id": "PERSISTENCIA", "horizonte_periodos": 1,
            "periodo_origem": origem, "alvo_periodo": alvo,
            "emitido_em": instant(origem),
            "dados_disponiveis_ate": instant(origem, 17),
            "treino_disponivel_ate": instant(origem, 17),
            "observado_publicado_em": instant(alvo),
            "observado_coletado_em": instant(alvo, 19),
            "edicao_sha256": SHA, "valor_base": v, "previsto": p,
            "baseline": v, "real": r,
        })
    return rows


def avaliar(rows, **overrides):
    cfg = dict(calendario=CAL, serie_id="CBOT_SOJA_NOV26",
               modelo_id="MOD1", unidade="USC/BU", baseline_id="PERSISTENCIA",
               horizonte_periodos=1, as_of_avaliacao=instant(CAL[80]), min_folds=5)
    cfg.update(overrides)
    return avaliar_previsoes_oos(rows, **cfg)


def nova():
    return {"serie_id": "CBOT_SOJA_NOV26", "modelo_id": "MOD1",
            "unidade": "USC/BU", "baseline_id": "PERSISTENCIA",
            "horizonte_periodos": 1, "periodo_origem": CAL[80],
            "alvo_periodo": CAL[81], "emitido_em": instant(CAL[80]),
            "dados_disponiveis_ate": instant(CAL[80], 17),
            "treino_disponivel_ate": instant(CAL[80], 17),
            "valor_base": 100, "previsto": 104}


class ValidacaoQuantitativa(unittest.TestCase):
    def test_baseline_mae_rmse_bias_e_gates(self):
        x = avaliar(arquivo(35))
        self.assertEqual(x["n_folds"], 35)
        self.assertAlmostEqual(x["mae"], 1)
        self.assertAlmostEqual(x["rmse"], 1)
        self.assertFalse(x["publicavel"])
        self.assertIsNone(x["brier_multiclasse_medio"])

    def test_nega_lookahead_feature_e_train(self):
        for campo in ("dados_disponiveis_ate", "treino_disponivel_ate"):
            rows = arquivo(35)
            rows[0][campo] = instant(rows[0]["alvo_periodo"])
            with self.subTest(campo=campo), self.assertRaisesRegex(ErroQuantitativo, "vazamento"):
                avaliar(rows)

    def test_nega_label_nao_publicado_antes_da_avaliacao(self):
        rows = arquivo()
        rows[-1]["observado_coletado_em"] = instant(CAL[90])
        with self.assertRaises(ErroQuantitativo):
            avaliar(rows)

    def test_nega_horizonte_calendario_modelo_unidade_e_duplicata(self):
        for campo, valor in (("horizonte_periodos", 2), ("unidade", "BRL/T"),
                             ("modelo_id", "OUTRO"), ("alvo_periodo", CAL[50])):
            rows = arquivo()
            rows[3][campo] = valor
            with self.subTest(campo=campo), self.assertRaises(ErroQuantitativo):
                avaliar(rows)
        with self.assertRaisesRegex(ErroQuantitativo, "repetida"):
            avaliar(arquivo()+[arquivo()[0]])

    def test_rejeita_bool_nan_inf_e_intervalo_invertido(self):
        for x in (True, float("nan"), float("inf")):
            rows = arquivo()
            rows[0]["previsto"] = x
            with self.subTest(x=str(x)), self.assertRaises(ErroQuantitativo):
                avaliar(rows)
        rows = arquivo()
        for row in rows:
            row.update(intervalo_inferior=90, intervalo_superior=110, nivel_intervalo=.9)
        self.assertEqual(avaliar(rows)["cobertura_intervalo"], 1)
        rows[0]["intervalo_inferior"] = 111
        with self.assertRaises(ErroQuantitativo):
            avaliar(rows)

    def test_multiclass_brier_e_bandas_sem_confundir_pesos(self):
        rows = arquivo()
        for r in rows:
            r["probabilidades"] = {"ALTA": 0.6, "ESTABILIDADE": .2, "BAIXA": .2}
        a = avaliar(rows, tolerancia_absoluta=1.5)
        self.assertGreaterEqual(a["brier_multiclasse_medio"], 0)
        self.assertLessEqual(a["brier_multiclasse_medio"], 2/3)
        self.assertIsNotNone(a["acuracia_direcional"])
        rows[0]["probabilidades"]["ALTA"] = .9
        with self.assertRaises(ErroQuantitativo):
            avaliar(rows, tolerancia_absoluta=1.5)

    def test_probabilidade_empirica_nao_homologada(self):
        x = tendencia_empirica_oos(
            nova(), arquivo(35), calendario=CAL, as_of=instant(CAL[80]),
            tolerancia_absoluta=1,
        )
        self.assertAlmostEqual(sum(x["probabilidades_empiricas_nao_calibradas"].values()), 1)
        self.assertEqual(x["tendencia"], "ALTA")
        self.assertIsNone(x["probabilidades_calibradas"])
        self.assertFalse(x["publicavel"])

    def test_nao_permite_residuos_futuros_no_modelo_empirico(self):
        rows = arquivo(35)
        rows[0]["observado_coletado_em"] = instant(CAL[85])
        with self.assertRaises(ErroQuantitativo):
            tendencia_empirica_oos(nova(), rows, calendario=CAL,
                                   as_of=instant(CAL[80]), tolerancia_absoluta=1)

    def test_residuos_insuficientes_e_fonte_misturada(self):
        with self.assertRaises(ErroQuantitativo):
            tendencia_empirica_oos(nova(), arquivo(20), calendario=CAL,
                                   as_of=instant(CAL[80]), tolerancia_absoluta=1)
        rows = arquivo()
        rows[0]["serie_id"] = "OUTRA_SERIE"
        with self.assertRaises(ErroQuantitativo):
            tendencia_empirica_oos(nova(), rows, calendario=CAL,
                                   as_of=instant(CAL[80]), tolerancia_absoluta=1)

    def test_folds_asof_revision_sem_vazamento(self):
        obs = []
        for i in range(8):
            dt = CAL[i]
            obs.append({"periodo": dt, "valor": 10+i,
                        "publicado_em": instant(dt, 16),
                        "coletado_em": instant(dt, 17),
                        "edicao_sha256": SHA})
        obs.append({"periodo": CAL[3], "valor": 999,
                    "publicado_em": instant(CAL[6], 16),
                    "coletado_em": instant(CAL[6], 17), "edicao_sha256": "b"*64})
        folds = preparar_folds_asof(
            obs, calendario=CAL, origens_em={CAL[5]: instant(CAL[5])},
            as_of_avaliacao=instant(CAL[10]),
            horizonte_periodos=1, minimo_treino=4,
        )
        self.assertEqual(folds[0]["alvo_periodo"], CAL[6])
        self.assertEqual(folds[0]["treino_asof"][1]["valor"], 13)
        self.assertEqual(folds[0]["real_avaliacao"], 16)

    def test_folds_bloqueiam_lacuna_e_revisao_exante(self):
        obs = [{"periodo": CAL[i], "valor": i+1,
                "publicado_em": instant(CAL[i], 16),
                "coletado_em": instant(CAL[i], 17),
                "edicao_sha256": SHA} for i in range(8) if i != 4]
        with self.assertRaisesRegex(ErroQuantitativo, "incompleto"):
            preparar_folds_asof(obs, calendario=CAL,
                origens_em={CAL[5]: instant(CAL[5])},
                as_of_avaliacao=instant(CAL[10]),
                horizonte_periodos=1, minimo_treino=4)


if __name__ == "__main__":
    unittest.main()
