import json
import unittest

from nivon.open_meteo_publico import (
    ARCHIVE_API, FORECAST_API, ErroOpenMeteo, normalizar_diario,
    planejar_consulta,
)

COL = "2026-10-21T12:00:00-04:00"


def exemplo(**extras):
    base = {
        "latitude": -13.0, "longitude": -56.0,
        "timezone": "GMT", "utc_offset_seconds": 0,
        "daily_units": {"time": "iso8601", "precipitation_sum": "mm",
                        "temperature_2m_max": "°C", "temperature_2m_min": "°C"},
        "daily": {"time": ["2026-10-22", "2026-10-23"],
                  "precipitation_sum": [0, 13.2],
                  "temperature_2m_max": [31.5, 30.0],
                  "temperature_2m_min": [22.1, 23.0]},
    }
    base.update(extras)
    return base


def normalizar(doc=None, tipo="previsao", **opts):
    return normalizar_diario(json.dumps(exemplo() if doc is None else doc).encode(),
                            tipo=tipo, coletado_em=COL,
                            latitude_solicitada=-13.0,
                            longitude_solicitada=-56.0, **opts)


class TestOpenMeteoPublico(unittest.TestCase):
    def test_planejador_previsao_sem_rede(self):
        url = planejar_consulta(latitude=-13.0, longitude=-56.0,
                               tipo="previsao", dias_previsao=7)
        self.assertTrue(url.startswith(FORECAST_API + "?"))
        self.assertIn("forecast_days=7", url)
        self.assertIn("timezone=UTC", url)
        self.assertNotIn("apikey=", url)

    def test_planejador_arquivo_limita_janela(self):
        url = planejar_consulta(latitude=-13.0, longitude=-56.0,
                               tipo="reanalise", inicio="2026-09-01", fim="2026-09-07")
        self.assertTrue(url.startswith(ARCHIVE_API + "?"))
        self.assertIn("start_date=2026-09-01", url)
        with self.assertRaises(ErroOpenMeteo):
            planejar_consulta(latitude=-13.0, longitude=-56.0,
                              tipo="reanalise", inicio="2020-01-01", fim="2024-01-01")

    def test_validacao_coords_e_limites(self):
        for lat, lon, days in [(91, 0, 2), (-13, -181, 2), (-13, -56, 17),
                               (True, -56, 2), (-13, float("nan"), 2)]:
            with self.subTest(lat=lat, lon=lon, days=days), self.assertRaises(ErroOpenMeteo):
                planejar_consulta(latitude=lat, longitude=lon,
                                  tipo="previsao", dias_previsao=days)

    def test_forecast_tem_referencia_e_sem_data_publicacao(self):
        out = normalizar()
        self.assertEqual(out["dataset_id"], "OPEN_METEO_PREVISAO_DIARIA")
        self.assertEqual(out["itens"][0]["data_referencia"], "2026-10-22")
        self.assertEqual(out["itens"][0]["precipitation_sum"], 0.0)
        self.assertEqual(out["itens"][0]["coleta"], "2026-10-21T16:00:00+00:00")
        self.assertIsNone(out["itens"][0]["publicacao"])
        self.assertEqual(out["itens"][0]["observacao_ou_previsao"], "PROJETADO_MODELO")
        self.assertFalse(out["apto_backtest_asof_publicacao"])
        self.assertFalse(out["apto_publicacao_automatica"])
        self.assertEqual(out["quantidade"], 2)
        self.assertEqual(len(out["sha256_original"]), 64)

    def test_reanalise_nao_vira_observacao_da_estacao(self):
        out = normalizar(tipo="reanalise")
        self.assertEqual(out["dataset_id"], "OPEN_METEO_HISTORICO_REANALISE")
        self.assertEqual(out["itens"][0]["observacao_ou_previsao"], "REANALISE_MODELO")

    def test_unidade_incorreta_falha(self):
        d = exemplo()
        d["daily_units"]["precipitation_sum"] = "inch"
        with self.assertRaises(ErroOpenMeteo):
            normalizar(d)

    def test_nao_trocar_timezone_sem_contrato(self):
        for key, val in [("timezone", "America/Sao_Paulo"), ("utc_offset_seconds", -10800)]:
            d = exemplo(**{key: val})
            with self.assertRaises(ErroOpenMeteo):
                normalizar(d)

    def test_sem_chuva_nao_significa_zero(self):
        d = exemplo()
        for k in ("precipitation_sum", "temperature_2m_min", "temperature_2m_max"):
            d["daily"][k][0] = None
        with self.assertRaises(ErroOpenMeteo):
            normalizar(d)

    def test_nan_negativo_e_minima_maior_maxima(self):
        for d in [
            exemplo(daily={**exemplo()["daily"], "precipitation_sum": [-1, 0]}),
            exemplo(daily={**exemplo()["daily"], "temperature_2m_max": [float("nan"), 31]}),
            exemplo(daily={**exemplo()["daily"], "temperature_2m_min": [40, 23]}),
        ]:
            with self.subTest(d=d), self.assertRaises(ErroOpenMeteo):
                normalizar(d)

    def test_rejeitar_datas_repetidas_ou_forafuso(self):
        for dates in (["2026-10-22", "2026-10-22"], ["2026-10-23", "2026-10-22"],
                      ["2026-10-22T00:00", "2026-10-23"], ["2026-02-30", "2026-10-23"]):
            d = exemplo()
            d["daily"]["time"] = dates
            with self.assertRaises(ErroOpenMeteo):
                normalizar(d)

    def test_rejeita_array_incompleto(self):
        d = exemplo()
        d["daily"]["precipitation_sum"].pop()
        with self.assertRaises(ErroOpenMeteo):
            normalizar(d)

    def test_sem_erro_json_ou_chave_duplicada(self):
        for raw in (b"", b"[]", b'{"timezone":"GMT","timezone":"UTC"}', b"x"*2_000_001):
            with self.assertRaises(ErroOpenMeteo):
                normalizar_diario(raw, tipo="previsao", coletado_em=COL,
                                 latitude_solicitada=-13.0, longitude_solicitada=-56.0)

    def test_coleta_deve_ter_fuso(self):
        with self.assertRaises(ErroOpenMeteo):
            normalizar_diario(json.dumps(exemplo()).encode(), tipo="previsao",
                             coletado_em="2026-10-21T12:00:00",
                             latitude_solicitada=-13.0, longitude_solicitada=-56.0)


if __name__ == "__main__":
    unittest.main()
