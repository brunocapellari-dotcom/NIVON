"""Regressões de janelas físicas comparáveis entre INMET e NASA POWER."""
import copy
import hashlib
import unittest
from datetime import datetime, timedelta, timezone

from nivon.confronto_janelas_fisicas import confrontar_chuva_janelas_equivalentes
from nivon.inmet_horario_qc import ErroINMETHorario


def input_data(days=30, convention="INICIO_INTERVALO"):
    station = []
    grid = []
    ispan = []
    nspan = []
    csv_hash = hashlib.sha256(b"CSV INMET SIMULADO").hexdigest()
    nasa_hash = hashlib.sha256(b"NASA SNAPSHOT SIMULADO").hexdigest()
    origin = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(days):
        utc = origin + timedelta(days=i)
        day = utc.date().isoformat()
        station.append({
            "data_utc": day, "comparacao_grade_permitida": True,
            "chuva_rotulo_utc_mm": 10.0,
        })
        grid.append({
            "data_utc": day, "valor": 11.0, "unidade": "MM_DIA",
            "latitude_grade": -12.4, "longitude_grade": -55.6,
            "publicado_utc": "2025-02-05T12:00:00Z",
            "primeira_coleta_utc": "2025-02-06T12:00:00Z",
            "conteudo_sha256": nasa_hash,
        })
        start = utc if convention == "INICIO_INTERVALO" else utc - timedelta(hours=1)
        ending = start + timedelta(hours=24)
        ispan.append({
            "data_utc": day, "inicio_utc": start.isoformat(),
            "fim_utc": ending.isoformat(),
            "raw_csv_sha256": csv_hash,
            "evidencia_convecao": "CONVENCAO_SINTETICA_DOCUMENTADA_INMET",
        })
        nspan.append({
            "data_utc": day, "inicio_utc": utc.isoformat(),
            "fim_utc": (utc + timedelta(days=1)).isoformat(),
            "conteudo_sha256": nasa_hash,
            "evidencia_convecao": "CONVENCAO_SINTETICA_DOCUMENTADA_NASA",
        })
    diario = {
        "status": "DIARIO_PRELIMINAR_NAO_HOMOLOGADO",
        "estacao": "A904", "raw_sha256": csv_hash, "dias": station,
    }
    qc = {
        "aprovado": True, "estacao": "A904", "raw_sha256": csv_hash,
        "relatorio_sha256": hashlib.sha256(b"QC SIMULADO").hexdigest(),
    }
    return {
        "diario_inmet": diario, "grade_nasa": grid,
        "intervalos_estacao": ispan, "intervalos_grade": nspan,
        "coordenadas_estacao": (-12.4, -55.6), "qc_externo": qc,
        "fonte_coordenadas": "METADADO DA ESTACAO EXTERNO SINTETICO",
        "corte_coleta": "2026-01-01T12:00:00Z",
    }


class TestJanelasFisicas(unittest.TestCase):
    def test_janela_equivalente_30_dias_score_descritivo(self):
        out = confrontar_chuva_janelas_equivalentes(**input_data())
        self.assertEqual(out["janelas_fisicas_verificadas"], 30)
        self.assertTrue(out["janelas_temporalmente_equivalentes"])
        self.assertAlmostEqual(out["mae"], 1)
        self.assertFalse(out["skill_preditiva_comprovada"])
        self.assertFalse(out["evidencias_intervalo_auditadas_externamente"])
        self.assertFalse(out["homologado"])

    def test_estacao_fim_intervalo_nasa_inicio_proibido(self):
        args = input_data(convention="FIM_INTERVALO")
        with self.assertRaisesRegex(ErroINMETHorario, "não compartilham"):
            confrontar_chuva_janelas_equivalentes(**args)

    def test_intervalo_com_horas_23_ou_25_proibido(self):
        for hours in (23, 25):
            args = input_data()
            first = args["intervalos_grade"][0]
            dt = datetime.fromisoformat(first["inicio_utc"])
            first["fim_utc"] = (dt + timedelta(hours=hours)).isoformat()
            with self.subTest(hours=hours), self.assertRaises(ErroINMETHorario):
                confrontar_chuva_janelas_equivalentes(**args)

    def test_sha_incorreto_ou_sem_prova_fisica_proibido(self):
        args = input_data()
        args["intervalos_estacao"][0]["raw_csv_sha256"] = "a" * 64
        with self.assertRaisesRegex(ErroINMETHorario, "SHA"):
            confrontar_chuva_janelas_equivalentes(**args)
        args = input_data()
        args["intervalos_grade"][2]["evidencia_convecao"] = ""
        with self.assertRaisesRegex(ErroINMETHorario, "documentação"):
            confrontar_chuva_janelas_equivalentes(**args)

    def test_janela_sem_fuso_bloqueada(self):
        args = input_data()
        args["intervalos_estacao"][1]["inicio_utc"] = "2025-01-02T00:00:00"
        with self.assertRaisesRegex(ErroINMETHorario, "fuso"):
            confrontar_chuva_janelas_equivalentes(**args)

    def test_dia_ausente_ou_duplicado_sem_reparacao(self):
        args = input_data()
        args["intervalos_grade"].pop(1)
        with self.assertRaises(ErroINMETHorario):
            confrontar_chuva_janelas_equivalentes(**args)
        args = input_data()
        args["intervalos_estacao"][3] = copy.deepcopy(args["intervalos_estacao"][2])
        with self.assertRaises(ErroINMETHorario):
            confrontar_chuva_janelas_equivalentes(**args)

    def test_qc_da_estacao_nao_homologado_nao_produz_score(self):
        args = input_data()
        args["qc_externo"]["aprovado"] = False
        with self.assertRaises(ErroINMETHorario):
            confrontar_chuva_janelas_equivalentes(**args)

    def test_publicacao_nasa_tardia_proibida_pelo_motor_canônico(self):
        args = input_data()
        args["grade_nasa"][0]["publicado_utc"] = "2027-02-06T12:00:00Z"
        with self.assertRaises(ErroINMETHorario):
            confrontar_chuva_janelas_equivalentes(**args)

    def test_sem_30_pares_retorna_cobertura_insuficiente(self):
        args = input_data(days=29)
        out = confrontar_chuva_janelas_equivalentes(**args)
        self.assertEqual(out["status"], "COBERTURA_INSUFICIENTE_PARA_SCORE")
        self.assertNotIn("rmse", out)
        self.assertEqual(out["janelas_fisicas_verificadas"], 29)


if __name__ == "__main__":
    unittest.main()
