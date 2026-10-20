"""Regressões sintéticas de vazão; nenhuma estação real ou licença implícita."""
import copy
import unittest
from datetime import datetime, timedelta, timezone

from nivon.verificacao_vazao_asof import (
    ErroVerificacaoVazao, avaliar_hidrograma_asof,
)


def fixture(n=36):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        valid = base + timedelta(days=i + 2)
        issue = valid - timedelta(hours=24)
        pub = issue + timedelta(minutes=30)
        observed = 100.0 + i
        iso = lambda x: x.isoformat()
        rows.append({
            "estacao_id": "ANA_12345678", "versao_modelo": "modelo_v1",
            "referencia_vertical": "datum_local_ANA",
            "emitido_em": iso(issue),
            "previsao_publicada_em": iso(pub),
            "previsao_coletada_em": iso(pub + timedelta(minutes=1)),
            "valido_em": iso(valid),
            "features_publicadas_ate": iso(issue - timedelta(minutes=5)),
            "baseline_publicado_em": iso(issue),
            "observado_publicado_em": iso(valid + timedelta(hours=1)),
            "observado_coletado_em": iso(valid + timedelta(hours=2)),
            "observado_m3_s": observed, "previsto_m3_s": observed,
            "baseline_m3_s": observed + 10,
            "qualidade": "APROVADO", "modo_validacao": "FORA_AMOSTRA",
        })
    return rows


def run(rows):
    return avaliar_hidrograma_asof(
        registros=rows, estacao_id="ANA_12345678",
        modelo_id="pesquisa_bacias", versao_modelo="modelo_v1",
        referencia_vertical="datum_local_ANA",
        horizonte_horas=24, passo_horas=24,
        fonte_observada="ANA_HidroWeb_snapshot_test",
        fonte_baseline="baseline_persistencia_snapshot_test",
    )


class VerificacaoVazaoTests(unittest.TestCase):
    def test_previsao_perfeita_conserva_volume_e_kge(self):
        result = run(fixture())
        self.assertAlmostEqual(result["mae_m3_s"], 0)
        self.assertAlmostEqual(result["nse"], 1)
        self.assertAlmostEqual(result["kge"]["kge_2009"], 1)
        self.assertAlmostEqual(result["erro_volume_m3"], 0)
        self.assertAlmostEqual(result["erro_horario_pico_horas"], 0)
        self.assertAlmostEqual(result["skill_mse_baseline"], 1)
        self.assertFalse(result["homologado"])
        self.assertFalse(result["origem_vintages_auditada_externamente"])
        self.assertAlmostEqual(result["antecedencia_efetiva_minima_horas"], 23.5)

    def test_erro_constante_volumetrico_fisicamente_consistente(self):
        rows = fixture()
        for row in rows:
            row["previsto_m3_s"] += 5
        res = run(rows)
        self.assertAlmostEqual(res["bias_m3_s"], 5)
        self.assertAlmostEqual(res["rmse_m3_s"], 5)
        self.assertAlmostEqual(res["skill_mse_baseline"], 0.75)
        self.assertAlmostEqual(res["erro_volume_m3"], 5 * len(rows) * 86400)
        self.assertLess(res["kge"]["kge_2009"], 1)

    def test_sem_variancia_nao_inventa_nse_kge(self):
        rows = fixture()
        for row in rows:
            row["observado_m3_s"] = 40
            row["previsto_m3_s"] = 40
            row["baseline_m3_s"] = 45
        res = run(rows)
        self.assertIsNone(res["nse"])
        self.assertIsNone(res["kge"]["kge_2009"])
        self.assertIsNone(res["erro_horario_pico_horas"])

    def test_nao_mistura_estacao_versao_datum(self):
        for k, v in (("estacao_id", "ANA_OUTRA_ESTACAO"),
                     ("versao_modelo", "v2"), ("referencia_vertical", "outro_datum")):
            rows = fixture()
            rows[3][k] = v
            with self.subTest(k=k), self.assertRaises(ErroVerificacaoVazao):
                run(rows)

    def test_falhas_temporais_bloqueadas(self):
        alterations = [
            ("features_publicadas_ate", lambda x: x["valido_em"]),
            ("previsao_publicada_em", lambda x: x["valido_em"]),
            ("previsao_coletada_em", lambda x: x["observado_publicado_em"]),
            ("baseline_publicado_em", lambda x: x["valido_em"]),
            ("observado_publicado_em", lambda x: x["emitido_em"]),
            ("observado_coletado_em", lambda x: x["emitido_em"]),
        ]
        for key, fn in alterations:
            rows = fixture()
            rows[2][key] = fn(rows[2])
            with self.subTest(key=key), self.assertRaises(ErroVerificacaoVazao):
                run(rows)

    def test_duplicate_e_gap_sao_bloqueados(self):
        rows = fixture()
        rows[7] = copy.deepcopy(rows[6])
        with self.assertRaises(ErroVerificacaoVazao):
            run(rows)
        rows = fixture()
        rows.pop(5)
        with self.assertRaises(ErroVerificacaoVazao):
            run(rows)

    def test_auditabilidade_nao_e_flag_de_homologacao(self):
        rows = fixture()
        rows[0]["modo_validacao"] = "TREINO"
        with self.assertRaises(ErroVerificacaoVazao):
            run(rows)
        rows = fixture()
        rows[1]["qualidade"] = "SUSPEITO"
        with self.assertRaises(ErroVerificacaoVazao):
            run(rows)

    def test_faltantes_booleanos_nan_e_negativos_bloqueados(self):
        for bad in (None, -1, float("nan"), True, "40", float("inf")):
            rows = fixture()
            rows[3]["observado_m3_s"] = bad
            with self.subTest(bad=bad), self.assertRaises(ErroVerificacaoVazao):
                run(rows)

    def test_tamanho_amostral_nao_pode_ser_burlado(self):
        with self.assertRaises(ErroVerificacaoVazao):
            run(fixture(29))
        with self.assertRaises(ErroVerificacaoVazao):
            avaliar_hidrograma_asof(
                registros=fixture(29), estacao_id="ANA_12345678",
                modelo_id="pesquisa_bacias", versao_modelo="modelo_v1",
                referencia_vertical="datum_local_ANA", horizonte_horas=24,
                passo_horas=24, fonte_observada="ANA_teste",
                fonte_baseline="base_teste", minimo=29,
            )

    def test_horizonte_e_timezone_obrigatorios(self):
        rows = fixture()
        rows[1]["valido_em"] = "2026-01-04T00:00:00"
        with self.assertRaises(ErroVerificacaoVazao):
            run(rows)
        rows = fixture()
        rows[1]["emitido_em"] = rows[1]["previsao_publicada_em"]
        with self.assertRaises(ErroVerificacaoVazao):
            run(rows)


if __name__ == "__main__":
    unittest.main()
