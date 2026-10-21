import json
import unittest
from datetime import datetime, timezone

from nivon.isric_soilgrids import (
    ErroSoilGrids, consultar_solo, normalizar_solo, planejar_solo,
)


def amostra():
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-56.0, -13.0]},
        "properties": {"layers": [{
            "name": "phh2o",
            "unit_measure": {"d_factor": 10, "mapped_units": "pH*10", "target_units": "pH"},
            "depths": [{"label": "0-5cm", "values": {"mean": 58, "Q05": 50, "Q95": 67}}],
        }]},
    }


class Resp:
    status = 200
    headers = {"Content-Type": "application/json"}
    def __init__(self, url, data): self.url, self.data = url, data
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def geturl(self): return self.url
    def read(self, n): return self.data[:n]


class Abridor:
    def __init__(self, data): self.data=data; self.calls=[]
    def open(self, req, timeout):
        self.calls.append(req.full_url)
        return Resp(req.full_url, self.data)


class TestSoloISRIC(unittest.TestCase):
    def test_url_sem_injecao_e_limite_de_coord(self):
        url = planejar_solo(latitude=-13, longitude=-56, propriedade="phh2o")
        self.assertTrue(url.startswith("https://rest.isric.org/soilgrids/v2.0/properties/query?"))
        for prop in ("receituario", "phh2o&lat=0", "../foo"):
            with self.assertRaises(ErroSoilGrids):
                planejar_solo(latitude=-13, longitude=-56, propriedade=prop)
        with self.assertRaises(ErroSoilGrids):
            planejar_solo(latitude=91, longitude=-56, propriedade="phh2o")

    def test_parser_converte_fator_sem_inventar_amostra_de_solo(self):
        dado = normalizar_solo(json.dumps(amostra()).encode(),
                              latitude=-13, longitude=-56,
                              propriedade="phh2o", profundidade="0-5cm",
                              estimativa="mean", coletado_em="2026-10-21T15:00:00-04:00")
        self.assertEqual(dado["valor_bruto"], 58)
        self.assertAlmostEqual(dado["valor_fisico_estimado"], 5.8)
        self.assertEqual(dado["unidade_fisica"], "pH")
        self.assertIn("NAO_AMOSTRA", dado["natureza"])
        self.assertFalse(dado["apto_recomendacao_agronomica"])
        self.assertFalse(dado["apto_publicacao_automatica"])
        self.assertIsNone(dado["publicacao"])

    def test_consulta_pontual_deny_default_e_mock_end_to_end(self):
        ab = Abridor(json.dumps(amostra()).encode())
        with self.assertRaises(PermissionError):
            consultar_solo(latitude=-13, longitude=-56, propriedade="phh2o", abridor=ab)
        self.assertEqual(ab.calls, [])
        r = consultar_solo(latitude=-13, longitude=-56, propriedade="phh2o",
                           executar=True, abridor=ab, instante=datetime(2026, 10, 21, 19, tzinfo=timezone.utc))
        self.assertEqual(len(ab.calls), 1)
        self.assertEqual(r["dados"]["valor_fisico_estimado"], 5.8)
        self.assertEqual(len(r["aquisição"]["sha256"]), 64)

    def test_invalido_fator_zero_ou_pixel_divergente(self):
        for doc in (
            {"type": "Feature", "properties": {"layers": []}},
            {**amostra(), "geometry": {"coordinates": [-20.0, -13.0]}},
            {"properties": {"layers": [{"name": "phh2o",
                       "unit_measure": {"d_factor": 0, "target_units": "pH"},
                       "depths": [{"label": "0-5cm", "values": {"mean": 58}}]}]}},
        ):
            with self.subTest(doc=doc), self.assertRaises(ErroSoilGrids):
                normalizar_solo(json.dumps(doc).encode(), latitude=-13, longitude=-56,
                                propriedade="phh2o", profundidade="0-5cm", estimativa="mean",
                                coletado_em="2026-10-21T19:00:00Z")

    def test_nao_aceita_coleta_sem_fuso(self):
        with self.assertRaises(ErroSoilGrids):
            normalizar_solo(json.dumps(amostra()).encode(), latitude=-13, longitude=-56,
                            propriedade="phh2o", profundidade="0-5cm", estimativa="mean",
                            coletado_em="2026-10-21T15:00:00")


if __name__ == "__main__":
    unittest.main()
