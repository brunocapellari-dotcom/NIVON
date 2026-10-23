"""Regressões sintéticas para ligação do contrato INMET horário -> backtest."""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from nivon.adaptador_inmet_chuva import (
    ErroAdaptadorINMET, converter_dia_inmet_para_snapshot,
)
from nivon.pacotes_chuva_asof import (
    ErroPacoteChuva, montar_e_verificar_pares_chuva,
)


def input_diario(ymd="2026-01-07", rain=12.0):
    return {
        "dataset_id": "INMET_ESTACOES",
        "estacao": "A904",
        "raw_sha256": hashlib.sha256(ymd.encode()).hexdigest(),
        "status": "DIARIO_PRELIMINAR_NAO_HOMOLOGADO",
        "liberacao_preditiva": False,
        "referencia_convencao": "MANUAL_HORA_INMET_SINTETICO",
        "dias": [{
            "data_utc": ymd, "horas_encontradas": 24, "horas_chuva_validas": 24,
            "convencao_intervalo_confirmada": True,
            "comparacao_grade_permitida": True,
            "qc_sensor": "NAO_HOMOLOGADO",
            "classificacao": "AGREGACAO_ESTACAO_SEM_QC",
            "chuva_rotulo_utc_mm": rain,
        }],
    }


def fixture(ymd="2026-01-07", rain=12.0, convencao="FIM_INTERVALO"):
    agregado = input_diario(ymd, rain)
    qc = {
        "estacao_id": "A904", "data_rotulo_utc": ymd,
        "raw_csv_sha256": agregado["raw_sha256"],
        "convencao_hora": convencao,
        "referencia_convencao": agregado["referencia_convencao"],
        "resultado": "APROVADO",
        "validado_em": (datetime.fromisoformat(ymd).replace(tzinfo=timezone.utc)
                        + timedelta(days=2)).isoformat(),
        "auditor_id": "AUDITOR_EXTERNO_SIMULADO",
    }
    return {
        "agregado": agregado, "data_rotulo_utc": ymd,
        "convencao_hora": convencao,
        "relatorio_qc_bytes": json.dumps(qc, sort_keys=True).encode(),
        "observacao_publicada_em": qc["validado_em"],
        "qc_publicado_em": qc["validado_em"],
        "coletado_em": (datetime.fromisoformat(qc["validado_em"]) + timedelta(hours=1)).isoformat(),
        "prova_disponibilidade_sha256": hashlib.sha256(b"manifesto-pit-sintetico").hexdigest(),
    }


def change_qc(args, fn):
    args = copy.deepcopy(args)
    qc = json.loads(args["relatorio_qc_bytes"])
    fn(qc)
    args["relatorio_qc_bytes"] = json.dumps(qc, sort_keys=True).encode()
    return args


class TestAdaptadorINMETChuva(unittest.TestCase):
    def test_fim_intervalo_24h_e_cadeia_sha(self):
        result = converter_dia_inmet_para_snapshot(**fixture())
        self.assertEqual(result["periodo_fisico_inicio_utc"], "2026-01-06T23:00:00+00:00")
        self.assertEqual(result["periodo_fisico_fim_utc"], "2026-01-07T23:00:00+00:00")
        snap = result["snapshot"]
        self.assertEqual(hashlib.sha256(snap["bytes_json"]).hexdigest(),
                         snap["manifesto"]["sha256"])
        row = json.loads(snap["bytes_json"])["registro"]
        self.assertEqual(row["observado_mm"], 12)
        self.assertEqual(row["qc_evidencia_sha256"], result["relatorio_qc_sha256"])
        self.assertEqual(row["estacao_id"], "INMET_A904")
        self.assertFalse(result["homologado"])
        self.assertFalse(result["qc_relatorio_autenticado_externamente"])

    def test_inicio_intervalo_24h_muda_janela_fisica(self):
        result = converter_dia_inmet_para_snapshot(**fixture(convencao="INICIO_INTERVALO"))
        self.assertEqual(result["periodo_fisico_inicio_utc"], "2026-01-07T00:00:00+00:00")
        self.assertEqual(result["periodo_fisico_fim_utc"], "2026-01-08T00:00:00+00:00")

    def test_zero_e_chuva_extrema_com_limitacao(self):
        a = converter_dia_inmet_para_snapshot(**fixture(rain=0))
        self.assertEqual(json.loads(a["snapshot"]["bytes_json"])["registro"]["observado_mm"], 0)
        for bad in (None, -2, float("nan"), float("inf"), 1001, True, "3"):
            args = fixture()
            args["agregado"]["dias"][0]["chuva_rotulo_utc_mm"] = bad
            with self.subTest(value=bad), self.assertRaises(ErroAdaptadorINMET):
                converter_dia_inmet_para_snapshot(**args)

    def test_exige_24_horas_sem_imputacao(self):
        for k, val in (("horas_encontradas", 23), ("horas_chuva_validas", 22),
                       ("comparacao_grade_permitida", False),
                       ("convencao_intervalo_confirmada", False),
                       ("qc_sensor", "APROVADO")):
            args = fixture()
            args["agregado"]["dias"][0][k] = val
            with self.subTest(field=k), self.assertRaises(ErroAdaptadorINMET):
                converter_dia_inmet_para_snapshot(**args)

    def test_qc_relatorio_precisa_estacao_dia_hash_e_convencao_corretos(self):
        for key, value in (("estacao_id", "A905"), ("data_rotulo_utc", "2026-01-08"),
                           ("raw_csv_sha256", "a" * 64),
                           ("convencao_hora", "INICIO_INTERVALO"),
                           ("referencia_convencao", "FALSA"),
                           ("resultado", "SUSPEITO"), ("auditor_id", "")):
            args = change_qc(fixture(), lambda qc: qc.update({key: value}))
            with self.subTest(field=key), self.assertRaises(ErroAdaptadorINMET):
                converter_dia_inmet_para_snapshot(**args)

    def test_qc_nao_pode_ser_aceito_antes_do_fim_do_periodo(self):
        args = change_qc(fixture(), lambda qc: qc.update(
            validado_em="2026-01-07T12:00:00Z"))
        with self.assertRaises(ErroAdaptadorINMET):
            converter_dia_inmet_para_snapshot(**args)

    def test_coleta_antes_publicacao_bloqueada(self):
        args = fixture()
        args["qc_publicado_em"] = "2026-01-09T09:00:00Z"
        args["coletado_em"] = "2026-01-09T08:00:00Z"
        with self.assertRaises(ErroAdaptadorINMET):
            converter_dia_inmet_para_snapshot(**args)

    def test_publicacao_observacao_posterior_ao_qc_define_vintage_efetiva(self):
        args = fixture()
        args["observacao_publicada_em"] = "2026-01-10T00:00:00Z"
        args["coletado_em"] = "2026-01-11T00:00:00Z"
        r = converter_dia_inmet_para_snapshot(**args)
        row = json.loads(r["snapshot"]["bytes_json"])["registro"]
        self.assertEqual(row["obs_publicado_em"], "2026-01-10T00:00:00+00:00")

    def test_data_duplicada_ou_ausente_bloqueada(self):
        args = fixture()
        args["agregado"]["dias"].append(copy.deepcopy(args["agregado"]["dias"][0]))
        with self.assertRaisesRegex(ErroAdaptadorINMET, "não único"):
            converter_dia_inmet_para_snapshot(**args)
        args = fixture()
        args["data_rotulo_utc"] = "2026-01-08"
        with self.assertRaises(ErroAdaptadorINMET):
            converter_dia_inmet_para_snapshot(**args)

    def test_qc_json_chave_duplicada_bloqueada(self):
        args = fixture()
        args["relatorio_qc_bytes"] = b'{"resultado":"APROVADO","resultado":"APROVADO"}'
        with self.assertRaisesRegex(ErroAdaptadorINMET, "chave duplicada"):
            converter_dia_inmet_para_snapshot(**args)

    def test_adaptador_montagem_nwp_30_intervalos_alinhados(self):
        observations = []
        forecasts = []
        for i in range(30):
            day = (datetime(2026, 1, 7, tzinfo=timezone.utc)
                   + timedelta(days=i)).date().isoformat()
            x = fixture(day, float(i % 8))
            result = converter_dia_inmet_para_snapshot(**x)
            obs = result["snapshot"]
            observations.append(obs)
            valid = datetime.fromisoformat(result["periodo_fisico_fim_utc"])
            issue = valid - timedelta(hours=48)
            forecast_row = {
                "estacao_id": "INMET_A904", "produto_id": "GEFS_FIXTURE",
                "versao_produto": "model_test_v1",
                "emitido_em": issue.isoformat(),
                "previsao_publicada_em": (issue + timedelta(minutes=10)).isoformat(),
                "features_publicadas_ate": (issue - timedelta(hours=1)).isoformat(),
                "climatologia_publicada_em": (issue - timedelta(days=10)).isoformat(),
                "valido_em": valid.isoformat(),
                "membros_mm": [float(i % 8)] * 5,
                "prob_climatologica": 0.5,
            }
            raw = json.dumps({"registro": forecast_row}, sort_keys=True).encode()
            forecasts.append({
                "manifesto": {
                    "dataset_id": "NOAA_GFS", "fonte_id": "NOAA",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "capturado_em": (issue + timedelta(minutes=30)).isoformat(),
                    "classe": "SINTETICO",
                    "prova_disponibilidade_sha256": hashlib.sha256(b"teste").hexdigest(),
                },
                "bytes_json": raw,
            })
        result = montar_e_verificar_pares_chuva(
            snapshots_previsao=forecasts,
            snapshots_observacao=observations,
            estacao_id="INMET_A904", produto_id="GEFS_FIXTURE",
            versao_produto="model_test_v1", horizonte_horas=48,
            acumulacao_horas=24, passo_horas=24,
            limiar_evento_mm=5, fonte_climatologia="CLIM_FIXTURE")
        self.assertEqual(result["avaliacao"]["n"], 30)
        self.assertAlmostEqual(result["avaliacao"]["crps_medio_mm"], 0)
        self.assertEqual(result["pacotes_raw_verificados_por_hash"], 60)
        self.assertFalse(result["homologado"])
        self.assertFalse(result["avaliacao"]["homologado"])


if __name__ == "__main__":
    unittest.main()
