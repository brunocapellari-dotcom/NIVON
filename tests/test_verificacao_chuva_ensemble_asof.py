"""Testes sintéticos de intervalos de precipitação e integridade as-of."""
import copy
import unittest
from datetime import datetime, timedelta, timezone

from nivon.verificacao_chuva_ensemble_asof import (
    ErroVerificacaoChuva, verificar_chuva_ensemble_asof,
)


def fixture(n=36):
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        valid = origin + timedelta(days=i + 4)
        issue = valid - timedelta(hours=48)
        published = issue + timedelta(minutes=30)
        captured = issue + timedelta(hours=1)
        rain = float([0, 2, 12, 30][i % 4])
        rows.append({
            "estacao_id": "INMET_A001", "produto_id": "GFS_ENS_EXPERIMENTAL",
            "versao_produto": "gfs-test-v1",
            "suporte_temporal": "ACUMULADO_INTERVALO",
            "emitido_em": issue.isoformat(),
            "previsao_publicada_em": published.isoformat(),
            "previsao_coletada_em": captured.isoformat(),
            "features_publicadas_ate": (issue - timedelta(hours=1)).isoformat(),
            "valido_em": valid.isoformat(),
            "obs_publicado_em": (valid + timedelta(hours=2)).isoformat(),
            "obs_coletado_em": (valid + timedelta(hours=3)).isoformat(),
            "climatologia_publicada_em": (issue - timedelta(days=1)).isoformat(),
            "observado_mm": rain, "membros_mm": [rain] * 5,
            "prob_climatologica": 0.5,
            "qc": "APROVADO", "modo_validacao": "FORA_AMOSTRA",
        })
    return rows


def evaluate(records, **kwargs):
    opts = dict(registros=records, estacao_id="INMET_A001",
                produto_id="GFS_ENS_EXPERIMENTAL",
                versao_produto="gfs-test-v1", limiar_evento_mm=10,
                horizonte_horas=48, acumulacao_horas=24,
                passo_horas=24, fonte_observacao="INMET_QC_SYNTHETIC",
                fonte_climatologia="CLIMATOLOGIA_SINTETICA")
    opts.update(kwargs)
    return verificar_chuva_ensemble_asof(**opts)


class TestChuvaEnsembleAsOf(unittest.TestCase):
    def test_ensemble_perfeito_tem_crps_brier_mae_zero(self):
        x = evaluate(fixture())
        self.assertEqual(x["n"], 36)
        self.assertEqual(x["membros"], 5)
        self.assertAlmostEqual(x["brier"], 0)
        self.assertAlmostEqual(x["crps_medio_mm"], 0)
        self.assertAlmostEqual(x["mae_media_ensemble_mm"], 0)
        self.assertAlmostEqual(x["brier_skill_climatologia"], 1)
        self.assertEqual(x["eventos_observados"], 18)
        self.assertAlmostEqual(x["antecedencia_minima_ao_inicio_horas"], 23)
        self.assertFalse(x["homologado"])
        self.assertFalse(x["calibracao_ensemble_validada"])

    def test_erro_precipitacao_conserva_unidades_sem_probabilidade_calibrada(self):
        rows = fixture()
        for row in rows:
            row["membros_mm"] = [row["observado_mm"] + 3] * 5
        x = evaluate(rows)
        self.assertAlmostEqual(x["bias_media_ensemble_mm"], 3)
        self.assertAlmostEqual(x["rmse_media_ensemble_mm"], 3)
        self.assertAlmostEqual(x["mae_media_ensemble_mm"], 3)
        self.assertAlmostEqual(x["crps_medio_mm"], 3)
        self.assertFalse(x["vintages_auditadas_externamente"])

    def test_dispersao_ensemble_reduz_falsa_precisao(self):
        rows = fixture()
        for row in rows:
            r = row["observado_mm"]
            row["membros_mm"] = [r, r, r + 2, r + 3, r + 4]
        x = evaluate(rows)
        self.assertGreater(x["crps_medio_mm"], 0)
        self.assertGreater(x["mae_media_ensemble_mm"], 0)

    def test_previsao_emitida_no_inicio_mas_capturada_dentro_do_intervalo_bloqueada(self):
        rows = fixture()
        row = rows[2]
        valid = datetime.fromisoformat(row["valido_em"])
        start = valid - timedelta(days=1)
        row["emitido_em"] = start.isoformat()
        row["previsao_publicada_em"] = (start + timedelta(minutes=5)).isoformat()
        row["previsao_coletada_em"] = (start + timedelta(minutes=10)).isoformat()
        with self.assertRaises(ErroVerificacaoChuva):
            evaluate(rows, horizonte_horas=24)

    def test_bloqueia_acumulacao_maior_que_horizonte(self):
        with self.assertRaises(ErroVerificacaoChuva):
            evaluate(fixture(), horizonte_horas=12)

    def test_bloqueia_sobreposicao_de_periodos(self):
        with self.assertRaises(ErroVerificacaoChuva):
            evaluate(fixture(), acumulacao_horas=48, passo_horas=24)

    def test_bloqueia_identidade_ou_versao_diferente(self):
        for field, value in (
            ("estacao_id", "INMET_OUTRO"), ("produto_id", "ERA5_REANALISE"),
            ("versao_produto", "gfs-v2"), ("suporte_temporal", "TAXA_MM_H"),
        ):
            rows = fixture()
            rows[1][field] = value
            with self.subTest(field=field), self.assertRaises(ErroVerificacaoChuva):
                evaluate(rows)

    def test_bloqueia_vintages_tardias_e_obs_futura(self):
        alterations = [
            ("features_publicadas_ate", lambda row: row["valido_em"]),
            ("previsao_publicada_em", lambda row: row["valido_em"]),
            ("previsao_coletada_em", lambda row: row["valido_em"]),
            ("climatologia_publicada_em", lambda row: row["valido_em"]),
            ("obs_publicado_em", lambda row: row["emitido_em"]),
            ("obs_coletado_em", lambda row: row["emitido_em"]),
        ]
        for field, change in alterations:
            rows = fixture()
            rows[2][field] = change(rows[2])
            with self.subTest(field=field), self.assertRaises(ErroVerificacaoChuva):
                evaluate(rows)

    def test_bloqueia_serie_incompleta_e_duplicada(self):
        rows = fixture()
        rows.pop(3)
        with self.assertRaises(ErroVerificacaoChuva):
            evaluate(rows)
        rows = fixture()
        rows[4] = copy.deepcopy(rows[3])
        with self.assertRaises(ErroVerificacaoChuva):
            evaluate(rows)

    def test_bloqueia_perda_de_membro_e_dados_invalidos(self):
        for bad in (None, -1, float("nan"), float("inf"), "0", True):
            rows = fixture()
            rows[5]["observado_mm"] = bad
            with self.subTest(value=bad), self.assertRaises(ErroVerificacaoChuva):
                evaluate(rows)
        rows = fixture()
        rows[4]["membros_mm"] = [3, 4, 5]
        with self.assertRaises(ErroVerificacaoChuva):
            evaluate(rows)

    def test_zero_observado_nao_e_faltante(self):
        x = evaluate(fixture())
        self.assertEqual(x["eventos_observados"], 18)
        self.assertEqual(sum(b["n"] for b in x["confiabilidade_por_faixas"]), 36)

    def test_brier_skill_nao_definido_se_baseline_perfeito(self):
        rows = fixture()
        for row in rows:
            row["prob_climatologica"] = float(row["observado_mm"] >= 10)
        x = evaluate(rows)
        self.assertIsNone(x["brier_skill_climatologia"])
        self.assertFalse(x["homologado"])

    def test_fusos_e_minimo_de_registros(self):
        rows = fixture()
        rows[2]["previsao_publicada_em"] = "2026-01-06T04:00:00"
        with self.assertRaises(ErroVerificacaoChuva):
            evaluate(rows)
        with self.assertRaises(ErroVerificacaoChuva):
            evaluate(fixture(29))
        with self.assertRaises(ErroVerificacaoChuva):
            evaluate(fixture(29), minimo=29)


if __name__ == "__main__":
    unittest.main()
