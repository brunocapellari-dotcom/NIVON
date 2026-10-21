"""Contrato real de parser INMET PR #9 até chuva NWP PR #19 (sintético).

Os 30 dias são deliberadamente sintéticos, mas passam pelo PARSER INMET
sem atalho por dicionários inventados no lugar das funções upstream.
Nenhum link privado, estação real ou publicação é acessado.
"""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from nivon.inmet_horario_qc import (
    ErroINMETHorario,
    agregar_dias_inmet,
    extrair_horarios_inmet,
)
from nivon.adaptador_inmet_chuva import ErroAdaptadorINMET, converter_dia_inmet_para_snapshot
from nivon.pacotes_chuva_asof import ErroPacoteChuva, montar_e_verificar_pares_chuva


def _csv_inmet(*, days=30, missing_hour=None, missing_rain=None):
    result = [
        "CODIGO (WMO):;A904",
        "ESTAÇÃO:;ESTACAO_TESTE",
        "Data;Hora UTC;PRECIPITAÇÃO TOTAL, HORÁRIO (mm);"
        "TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)",
    ]
    origin = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(days):
        day = (origin + timedelta(days=i)).date().isoformat()
        hourly = (0.0, 0.25, 0.5, 1.0)[i % 4]
        for hour in range(24):
            if missing_hour == (i, hour):
                continue
            rain = "" if missing_rain == (i, hour) else str(hourly).replace(".", ",")
            result.append(f"{day};{hour:02d}00 UTC;{rain};25,0")
    return ("\n".join(result) + "\n").encode("utf-8")


def _normalizado(csv, *, confirm=True):
    hour = extrair_horarios_inmet(
        csv_bytes=csv, estacao_esperada="A904", ano_esperado=2025)
    if not confirm:
        return hour, agregar_dias_inmet(pacote=hour)
    return hour, agregar_dias_inmet(
        pacote=hour,
        convencao_intervalo_chuva_confirmada=True,
        referencia_convencao="CONVENCAO_HORARIA_SINTETICA_NAO_OFICIAL",
    )


def _adapt(aggregate, date, *, convention="FIM_INTERVALO"):
    end_of_day = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    qc_validated = end_of_day + timedelta(days=2)
    qc_row = {
        "estacao_id": "A904", "data_rotulo_utc": date,
        "raw_csv_sha256": aggregate["raw_sha256"],
        "convencao_hora": convention,
        "referencia_convencao": aggregate["referencia_convencao"],
        "resultado": "APROVADO",
        "validado_em": qc_validated.isoformat(),
        "auditor_id": "AUDITOR_DE_TESTES_SEM_ASSINATURA",
    }
    return converter_dia_inmet_para_snapshot(
        agregado=aggregate, data_rotulo_utc=date,
        convencao_hora=convention,
        relatorio_qc_bytes=json.dumps(qc_row, sort_keys=True).encode(),
        observacao_publicada_em=qc_validated.isoformat(),
        qc_publicado_em=qc_validated.isoformat(),
        coletado_em=(qc_validated + timedelta(hours=1)).isoformat(),
        prova_disponibilidade_sha256=hashlib.sha256(
            ("EVIDENCIA_NAO_REAL:" + date).encode()).hexdigest(),
    )


def _forecast(valid, amount, *, i):
    issued = valid - timedelta(hours=48)
    item = {
        "estacao_id": "INMET_A904",
        "produto_id": "NWP_ENSEMBLE_TOTALMENTE_SINTETICO",
        "versao_produto": "fixture_v1", "emitido_em": issued.isoformat(),
        "previsao_publicada_em": (issued + timedelta(minutes=10)).isoformat(),
        "features_publicadas_ate": (issued - timedelta(minutes=1)).isoformat(),
        "climatologia_publicada_em": (issued - timedelta(days=1)).isoformat(),
        "valido_em": valid.isoformat(),
        "membros_mm": [amount] * 5,
        "prob_climatologica": 0.25,
    }
    raw = json.dumps({"registro": item}, sort_keys=True).encode()
    return {
        "manifesto": {
            "dataset_id": "NOAA_GFS", "fonte_id": "NOAA",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "capturado_em": (issued + timedelta(minutes=30)).isoformat(),
            "classe": "SINTETICO",
            "prova_disponibilidade_sha256": hashlib.sha256(
                ("TESTE_NAO_AUTENTICADO:" + str(i)).encode()).hexdigest(),
        },
        "bytes_json": raw,
    }


class TestIntegracaoParserINMETReal(unittest.TestCase):
    def test_parser_horario_24h_adaptador_raw_e_scores_30_dias(self):
        hour, aggregate = _normalizado(_csv_inmet())
        self.assertEqual(hour["linhas"], 720)
        self.assertEqual(len(aggregate["dias"]), 30)
        self.assertEqual(hour["status"], "BRUTO_HORARIO_SEM_QC")
        self.assertEqual(aggregate["status"], "DIARIO_PRELIMINAR_NAO_HOMOLOGADO")
        self.assertFalse(aggregate["liberacao_preditiva"])
        observed, forecasts, qc_hashes = [], [], set()
        for i, row in enumerate(aggregate["dias"]):
            prepared = _adapt(aggregate, row["data_utc"])
            observation = prepared["snapshot"]
            self.assertFalse(prepared["homologado"])
            self.assertEqual(prepared["csv_bruto_sha256"], hour["raw_sha256"])
            self.assertFalse(prepared["qc_relatorio_autenticado_externamente"])
            self.assertFalse(prepared["disponibilidade_historica_atestada_externamente"])
            qc_hashes.add(prepared["relatorio_qc_sha256"])
            valid = datetime.fromisoformat(prepared["periodo_fisico_fim_utc"])
            amount = row["chuva_rotulo_utc_mm"]
            self.assertEqual(amount, [0, 6, 12, 24][i % 4])
            observed.append(observation)
            forecasts.append(_forecast(valid, amount, i=i))
        self.assertEqual(len(qc_hashes), 30)
        result = montar_e_verificar_pares_chuva(
            snapshots_previsao=forecasts,
            snapshots_observacao=observed,
            estacao_id="INMET_A904",
            produto_id="NWP_ENSEMBLE_TOTALMENTE_SINTETICO",
            versao_produto="fixture_v1",
            horizonte_horas=48, acumulacao_horas=24, passo_horas=24,
            limiar_evento_mm=10, fonte_climatologia="CLIMATOLOGIA_FIXTURE")
        scores = result["avaliacao"]
        self.assertEqual(scores["n"], 30)
        self.assertEqual(result["pacotes_raw_verificados_por_hash"], 60)
        self.assertAlmostEqual(scores["brier"], 0)
        self.assertAlmostEqual(scores["crps_medio_mm"], 0)
        self.assertAlmostEqual(scores["mae_media_ensemble_mm"], 0)
        self.assertFalse(result["homologado"])
        self.assertFalse(scores["homologado"])
        self.assertFalse(result["prova_externa_vintages_validada"])
        self.assertFalse(result["qc_instrumental_validado_independentemente"])

    def test_parser_nao_preenche_chuva_horaria_faltante(self):
        hour, aggregate = _normalizado(_csv_inmet(missing_rain=(7, 3)))
        self.assertEqual(hour["linhas"], 720)
        day = aggregate["dias"][7]
        self.assertEqual(day["horas_encontradas"], 24)
        self.assertEqual(day["horas_chuva_validas"], 23)
        self.assertIsNone(day["chuva_rotulo_utc_mm"])
        with self.assertRaises(ErroAdaptadorINMET):
            _adapt(aggregate, day["data_utc"])

    def test_parser_nao_preenche_hora_ausente(self):
        _, aggregate = _normalizado(_csv_inmet(missing_hour=(9, 12)))
        day = aggregate["dias"][9]
        self.assertEqual(day["horas_encontradas"], 23)
        self.assertIsNone(day["chuva_rotulo_utc_mm"])
        with self.assertRaises(ErroAdaptadorINMET):
            _adapt(aggregate, day["data_utc"])

    def test_sem_convencao_documentada_nao_inferir_periodo(self):
        _, aggregate = _normalizado(_csv_inmet(days=1), confirm=False)
        self.assertFalse(aggregate["dias"][0]["comparacao_grade_permitida"])
        with self.assertRaises(ErroAdaptadorINMET):
            _adapt(aggregate, aggregate["dias"][0]["data_utc"])

    def test_convencao_inicio_e_fim_nao_sao_iguais(self):
        _, aggregate = _normalizado(_csv_inmet(days=1))
        day = aggregate["dias"][0]["data_utc"]
        finish = _adapt(aggregate, day, convention="FIM_INTERVALO")
        start = _adapt(aggregate, day, convention="INICIO_INTERVALO")
        self.assertNotEqual(finish["periodo_fisico_inicio_utc"],
                            start["periodo_fisico_inicio_utc"])
        self.assertEqual(finish["periodo_fisico_fim_utc"], "2025-01-01T23:00:00+00:00")
        self.assertEqual(start["periodo_fisico_fim_utc"], "2025-01-02T00:00:00+00:00")

    def test_erro_de_fuso_no_forecast_falha_sem_pares_parciais(self):
        _, aggregate = _normalizado(_csv_inmet())
        observed, forecasts = [], []
        for i, day in enumerate(aggregate["dias"]):
            prep = _adapt(aggregate, day["data_utc"])
            valid = datetime.fromisoformat(prep["periodo_fisico_fim_utc"])
            observed.append(prep["snapshot"])
            forecasts.append(_forecast(valid, day["chuva_rotulo_utc_mm"], i=i))
        obj = json.loads(forecasts[4]["bytes_json"])
        obj["registro"]["valido_em"] = obj["registro"]["valido_em"].replace("+00:00", "")
        raw = json.dumps(obj).encode()
        forecasts[4]["bytes_json"] = raw
        forecasts[4]["manifesto"]["sha256"] = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(ErroPacoteChuva):
            montar_e_verificar_pares_chuva(
                snapshots_previsao=forecasts, snapshots_observacao=observed,
                estacao_id="INMET_A904",
                produto_id="NWP_ENSEMBLE_TOTALMENTE_SINTETICO",
                versao_produto="fixture_v1", horizonte_horas=48,
                acumulacao_horas=24, passo_horas=24, limiar_evento_mm=10,
                fonte_climatologia="CLIMATOLOGIA_FIXTURE",
            )


if __name__ == "__main__":
    unittest.main()
