"""Regressoes sintéticas da auditoria temporal purgada do holdout."""
from datetime import date, timedelta
import unittest

from nivon.auditoria_holdout_quant import avaliar_holdout_temporal_purgado
from nivon.quant_core import ErroQuantitativo

DIAS = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(190)]
SHA = "d" * 64


def ts(dia, h=18):
    return dia + "T%02d:00:00Z" % h


def registros(*, horizonte=5, n=120, erro_modelo=0.0):
    out = []
    for i in range(20, 20 + n):
        origem = DIAS[i]
        alvo = DIAS[i + horizonte]
        base = 100.0 + i
        real = base + horizonte
        prev = real + erro_modelo
        out.append({
            "serie_id": "TESTE_CBOT_SOJA_NOV26", "modelo_id": "MODELO_1",
            "unidade": "USC/BU", "baseline_id": "PERSISTENCIA",
            "horizonte_periodos": horizonte,
            "periodo_origem": origem, "alvo_periodo": alvo,
            "emitido_em": ts(origem),
            "dados_disponiveis_ate": ts(origem, 17),
            "treino_disponivel_ate": ts(origem, 17),
            "observado_publicado_em": ts(alvo),
            "observado_coletado_em": ts(alvo, 19),
            "edicao_sha256": SHA, "valor_base": base,
            "previsto": prev, "baseline": base, "real": real,
        })
    return out


def auditar(rows, **kw):
    args = dict(
        calendario=DIAS, serie_id="TESTE_CBOT_SOJA_NOV26",
        modelo_id="MODELO_1", unidade="USC/BU",
        baseline_id="PERSISTENCIA", horizonte_periodos=5,
        as_of_avaliacao=ts(DIAS[189]), n_holdout=40,
        minimo_historico_elegivel=30, minimo_por_fase_disjunta=5,
    )
    args.update(kw)
    return avaliar_holdout_temporal_purgado(rows, **args)


class TestHoldoutPurgado(unittest.TestCase):
    def test_purga_desfechos_desconhecidos_e_todas_as_fases(self):
        r = auditar(registros())
        self.assertEqual(r["status"], "SINAL_DESCRITIVO_HOLDOUT_NAO_HOMOLOGADO")
        self.assertEqual(r["n_holdout"], 40)
        self.assertEqual(r["n_historico_elegivel"], 75)
        self.assertEqual(r["n_excluidos_pela_purga"], 5)
        self.assertEqual(r["quantidade_fases"], 5)
        self.assertEqual([x["n"] for x in r["metricas_fases_nao_sobrepostas"]], [8] * 5)
        self.assertAlmostEqual(r["metricas_holdout"]["mae_baseline"], 5)
        self.assertAlmostEqual(r["metricas_holdout"]["mae"], 0)
        self.assertTrue(r["superioridade_em_todas_as_fases"])
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["habilitado_para_producao"])
        self.assertIsNone(r["percentis_ou_significancia_iid"])

    def test_modelo_pior_que_persistencia_nao_aprovado(self):
        r = auditar(registros(erro_modelo=7))
        self.assertEqual(r["status"], "SEM_SUPERIORIDADE_ROBUSTA_AO_BASELINE")
        self.assertFalse(r["superioridade_em_todas_as_fases"])
        self.assertLess(r["metricas_holdout"]["ganho_mae_baseline"], 0)

    def test_uma_fase_fracassa_entao_nao_chamar_superioridade_robusta(self):
        rows = registros()
        for r in rows:
            i = DIAS.index(r["periodo_origem"])
            if i >= 100 and i % 5 == 3:
                r["previsto"] = r["real"] + 7
        x = auditar(rows)
        self.assertEqual(x["status"], "SEM_SUPERIORIDADE_ROBUSTA_AO_BASELINE")
        self.assertFalse(x["superioridade_em_todas_as_fases"])
        self.assertEqual(len([g for g in x["metricas_fases_nao_sobrepostas"]
                              if g["ganho_mae_baseline"] < 0]), 1)

    def test_amostra_holdout_insuficiente_nao_vira_metricas(self):
        r = auditar(registros(n=50))
        self.assertEqual(r["status"], "AMOSTRA_HOLDOUT_INSUFICIENTE")
        self.assertNotIn("metricas_holdout", r)
        self.assertFalse(r["publicavel"])

    def test_coleta_tardia_de_resultado_historico_nao_contamina_holdout(self):
        rows = registros()
        # Forecast antigo, mas o resultado atrasou ate depois da primeira
        # emissao do holdout; nao pode entrar no historico elegivel.
        rows[2]["observado_coletado_em"] = ts(DIAS[111], 19)
        r = auditar(rows)
        self.assertEqual(r["status"], "SINAL_DESCRITIVO_HOLDOUT_NAO_HOMOLOGADO")
        self.assertEqual(r["n_historico_elegivel"], 74)
        self.assertEqual(r["n_excluidos_pela_purga"], 6)
        self.assertFalse(r["publicavel"])

    def test_sem_ganho_real_baseline_igual_nao_sinaliza_superioridade(self):
        # Previsao igual a persistencia: ganho MAE/RMSE rigorosamente zero.
        r = auditar(registros(erro_modelo=-5))
        self.assertEqual(r["status"], "SEM_SUPERIORIDADE_ROBUSTA_AO_BASELINE")
        self.assertFalse(r["superioridade_em_todas_as_fases"])
        self.assertAlmostEqual(r["metricas_holdout"]["ganho_mae_baseline"], 0.0)

    def test_purga_mais_longa_invalida_treino(self):
        r = auditar(registros(), embargo_periodos=55)
        self.assertEqual(r["status"], "HISTORICO_PURGADO_INSUFICIENTE")
        self.assertFalse(r["publicavel"])
        self.assertEqual(r["n_historico_elegivel"], 21)

    def test_fases_insuficientes_nao_concluem_skill(self):
        r = auditar(registros(), n_holdout=20)
        self.assertEqual(r["status"], "FASES_DISJUNTAS_INSUFICIENTES")
        self.assertFalse(r["superioridade_em_todas_as_fases"])
        self.assertTrue(all(x["n"] == 4 for x in r["metricas_fases_nao_sobrepostas"]))

    def test_treino_retroativo_apos_emissao_bloqueia(self):
        rows = registros()
        rows[2]["treino_disponivel_ate"] = ts(DIAS[99])
        with self.assertRaisesRegex(ErroQuantitativo, "vazamento"):
            auditar(rows)

    def test_desfecho_apos_corte_final_bloqueia(self):
        rows = registros()
        rows[-1]["observado_coletado_em"] = ts(DIAS[189 + 0], 23)
        # Ainda antes do as_of 18:00? nao: 23:00 no mesmo dia.
        with self.assertRaisesRegex(ErroQuantitativo, "vazamento"):
            auditar(rows)

    def test_modelo_serie_horizonte_incompativeis_bloqueiam(self):
        for key, value in (
            ("serie_id", "FRETE_AGREGADO_MUNICIPAL"),
            ("horizonte_periodos", 4),
            ("unidade", "BRL/T"),
        ):
            rows = registros()
            rows[2][key] = value
            with self.subTest(campo=key), self.assertRaises(ErroQuantitativo):
                auditar(rows)

    def test_ordem_de_emissao_retroativa_bloqueia(self):
        rows = registros()
        rows[2]["emitido_em"] = ts(DIAS[23])
        rows[2]["dados_disponiveis_ate"] = ts(DIAS[22], 17)
        rows[2]["treino_disponivel_ate"] = ts(DIAS[22], 17)
        # Emissao de origem 22 apos emissao de origem 23 (indice seguinte).
        with self.assertRaisesRegex(ErroQuantitativo, "ordem temporal"):
            auditar(rows)

    def test_horizonte_um_sem_fases_sobrepostas(self):
        rows = registros(horizonte=1)
        r = auditar(rows, horizonte_periodos=1)
        self.assertEqual(r["quantidade_fases"], 1)
        self.assertEqual(r["metricas_fases_nao_sobrepostas"][0]["n"], 40)
        self.assertEqual(r["n_excluidos_pela_purga"], 1)

    def test_parametros_inseguros_ou_nao_inteiros(self):
        for cfg in (
            {"n_holdout": True},
            {"n_holdout": 4},
            {"minimo_historico_elegivel": 1},
            {"minimo_por_fase_disjunta": 4},
            {"embargo_periodos": 0},
            {"n_holdout": 20, "minimo_por_fase_disjunta": 25},
        ):
            with self.subTest(cfg=cfg), self.assertRaises(ErroQuantitativo):
                auditar(registros(), **cfg)


if __name__ == "__main__":
    unittest.main()
