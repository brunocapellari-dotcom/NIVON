"""Testes sem rede de NASA GLAM NDVI com dados de exemplo NÃO oficiais."""
import unittest
from datetime import datetime, timezone
from nivon.nasa_glam_ndvi import (
    ErroGLAM, consultar_ndvi, normalizar_csv_ndvi, planejar_ndvi,
)

CSV = b"day,ndvi_mean\n001,0.46\n009,0.50\n"
NOW = datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc)


class Resposta:
    def __init__(self, url, content=CSV, mime="text/csv", status=200, final=None):
        self.url, self.content, self.mime, self.status, self.final = url, content, mime, status, final
        self.headers = {"Content-Type": mime}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, n): return self.content[:n]
    def geturl(self): return self.final or self.url


class Abridor:
    def __init__(self, **kwargs): self.args=kwargs; self.urls=[]
    def open(self, req, timeout):
        self.urls.append(req.full_url)
        return Resposta(req.full_url, **self.args)


def parse(raw=CSV):
    return normalizar_csv_ndvi(raw, id_glam="110955", ano=2025, sensor="VNP",
                              inicio_mes=4, meses=8, modo="seasonal",
                              coletado_em="2026-10-21T15:00:00-04:00")


class TestGLAM(unittest.TestCase):
    def test_plano_sem_chave_e_id_nao_ibge(self):
        url = planejar_ndvi(id_glam="110955", ano=2025, inicio_mes=4, meses=8)
        self.assertIn("glam1.gsfc.nasa.gov/api/gettbl/v4?", url)
        self.assertIn("ids=110955", url)
        self.assertIn("layer=NDVI", url)
        self.assertNotIn("api_key", url)
        for id_ in ("id; rm -rf /", "012_494", "a", "", "-1", "1' OR 1=1"):
            with self.subTest(id_=id_), self.assertRaises(ErroGLAM):
                planejar_ndvi(id_glam=id_, ano=2025)
        for sensor in ("NOAA", "S2", "viirs"):
            with self.assertRaises(ErroGLAM):
                planejar_ndvi(id_glam="110955", ano=2025, sensor=sensor)

    def test_csv_nao_vira_produtividade_agricola(self):
        doc = parse()
        self.assertEqual(doc["n_linhas"], 2)
        self.assertEqual(doc["linhas_textuais"][0]["ndvi_mean"], "0.46")
        self.assertIsNone(doc["codigo_ibge"])
        self.assertFalse(doc["mascara_culturas_homologada"])
        self.assertFalse(doc["valores_ndvi_normalizados"])
        self.assertFalse(doc["apto_motor_produtividade"])
        self.assertIsNone(doc["publicacao"])
        self.assertEqual(doc["coleta"], "2026-10-21T19:00:00+00:00")

    def test_default_deny_e_uma_requisicao(self):
        abridor = Abridor()
        with self.assertRaises(PermissionError):
            consultar_ndvi(id_glam="110955", ano=2025, abridor=abridor)
        self.assertEqual(len(abridor.urls), 0)
        out = consultar_ndvi(id_glam="110955", ano=2025, executar=True,
                             abridor=abridor, instante=NOW)
        self.assertEqual(len(abridor.urls), 1)
        self.assertEqual(out["dados"]["n_linhas"], 2)
        self.assertEqual(len(out["aquisicao"]["sha256"]), 64)

    def test_fail_closed_para_http_e_csv_anormal(self):
        for bad in (b"<html>Forbidden</html>", b"", b"a,a\n1,2\n", b"a,b\n1\n", b"a,b\n1,2\n3\n"):
            with self.subTest(bad=bad), self.assertRaises(ErroGLAM):
                parse(bad)
        for config in ({"status": 429}, {"mime": "text/html"},
                       {"final": "https://malicioso.example/data.csv"}):
            abridor = Abridor(**config)
            with self.subTest(config=config), self.assertRaises(ErroGLAM):
                consultar_ndvi(id_glam="110955", ano=2025, executar=True,
                               abridor=abridor, instante=NOW)

    def test_somente_periodo_solicitado_e_utc(self):
        with self.assertRaises(ErroGLAM):
            planejar_ndvi(id_glam="110955", ano=2025, inicio_mes=12, meses=3)
        with self.assertRaises(ErroGLAM):
            normalizar_csv_ndvi(CSV, id_glam="110955", ano=2025, sensor="VNP",
                                inicio_mes=1, meses=12, modo="seasonal",
                                coletado_em="2026-10-21T15:00:00")


if __name__ == "__main__":
    unittest.main()
