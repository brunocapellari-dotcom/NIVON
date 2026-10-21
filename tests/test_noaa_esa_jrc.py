"""Testes NOAA MEI v2 e ESA/JRC sem rede."""
import unittest
from datetime import datetime, timezone
from nivon.noaa_mei_v2 import ErroMEI, normalizar_mei_csv, consultar_mei_v2
from nivon.georaster_catalogos import (
    planejar_esa, consultar_esa_tile, normalizar_jrc_wmts, consultar_jrc_wmts,
    ErroRasterCatalogo,
)

NOW = datetime(2026, 10, 21, 16, tzinfo=timezone.utc)
CSV = (b"YEAR,DJ,JF,FM,MA,AM,MJ,JJ,JA,AS,SO,ON,ND\n"
       b"2024,1,0.9,0.8,0.7,0.2,-0.1,-0.2,-0.4,-0.5,-0.8,-1,-1.2\n"
       b"2025,-999,-999,-999,-999,-999,-999,-999,-999,-999,-999,-999,-999\n")
XML = (b'<?xml version="1.0" encoding="UTF-8"?>'
       b'<Capabilities xmlns="http://www.opengis.net/wmts/1.0">'
       b'<Contents><Layer><Identifier xmlns="http://www.opengis.net/ows/1.1">'
       b'occurrence</Identifier></Layer></Contents></Capabilities>')


class Resp:
    def __init__(self, url, body, *, mime, length=None):
        self.url, self.body, self.status = url, body, 200
        self.headers = {"Content-Type": mime, "Content-Length": length or str(len(body))}
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def geturl(self): return self.url
    def read(self, n): return self.body[:n]


class Abridor:
    def __init__(self, body, mime, length=None):
        self.body, self.mime, self.length = body, mime, length
        self.calls=[]
    def open(self, req, timeout):
        self.calls.append((req.full_url, req.get_method()))
        return Resp(req.full_url, self.body, mime=self.mime, length=self.length)


class TestNOAAMEI(unittest.TestCase):
    def test_indice_bimestral_nao_mensal_inventado(self):
        r = normalizar_mei_csv(CSV, coletado_em="2026-10-21T12:00:00-04:00")
        self.assertEqual(r["quantidade"], 12)
        self.assertEqual(r["observacoes"][0]["bimestre_movel"], "DJ")
        self.assertEqual(r["observacoes"][0]["competencia"], "2024-01")
        self.assertIsNone(r["publicacao"])
        self.assertFalse(r["apto_backtest_asof"])

    def test_csv_oficial_real_com_data_mensal_e_indice_bimestral(self):
        raw = (b"Date, Multivariate ENSO Index Version 2 (MEI.v2) missing value -999\n"
               b"1979-01-01, 0.460\n1979-02-01, 0.290\n1979-03-01, -999\n")
        r = normalizar_mei_csv(raw, coletado_em="2026-10-21T16:00:00Z")
        self.assertEqual(r["quantidade"], 2)
        self.assertEqual(r["observacoes"][0]["data_referencia"], "1979-01-01")
        self.assertEqual(r["observacoes"][0]["bimestre_movel"], "DJ")
        self.assertEqual(r["observacoes"][1]["bimestre_movel"], "JF")

    def test_rede_bloqueada_sem_execute_e_pontual_quando_liberada(self):
        a = Abridor(CSV, "text/csv")
        with self.assertRaises(PermissionError):
            consultar_mei_v2(abridor=a)
        self.assertFalse(a.calls)
        r = consultar_mei_v2(executar=True, abridor=a, instante=NOW)
        self.assertEqual(len(a.calls), 1)
        self.assertEqual(r["dados"]["quantidade"], 12)

    def test_rejeita_csv_ambiguo(self):
        for raw in (b"YEAR,DJ,JF\n2024,1,2\n",
                    CSV.replace(b"2024", b"202Z"),
                    CSV.replace(b"0.9", b"nan"),
                    CSV.replace(b"-0.8", b"19.5")):
            with self.subTest(raw=raw[:60]), self.assertRaises(ErroMEI):
                normalizar_mei_csv(raw, coletado_em="2026-10-21T16:00:00Z")


class TestGeoMetadata(unittest.TestCase):
    def test_worldcover_tile_sul_oeste_sem_download(self):
        url = planejar_esa(latitude=-13, longitude=-56)
        self.assertEqual(url["tile"], "S15W057")
        self.assertIn("2021_v200_S15W057_Map.tif", url["url"])
        for lat, lon in ((-91, -56), (-13, 190), (float("nan"), -56)):
            with self.assertRaises(ErroRasterCatalogo):
                planejar_esa(latitude=lat, longitude=lon)
        a = Abridor(b"", "binary/octet-stream", "8790032")
        with self.assertRaises(PermissionError):
            consultar_esa_tile(latitude=-13, longitude=-56, abridor=a)
        self.assertEqual(a.calls, [])
        r = consultar_esa_tile(latitude=-13, longitude=-56,
                             executar=True, abridor=a, instante=NOW)
        self.assertTrue(r["raster_existe_por_head"])
        self.assertFalse(r["raster_baixado"])
        self.assertEqual(a.calls[0][1], "HEAD")

    def test_jrc_wmts_metadata_nao_finge_dado_agua(self):
        d = normalizar_jrc_wmts(XML, coletado_em="2026-10-21T16:00:00Z")
        self.assertEqual(d["camadas_publicas_wmts"], ["occurrence"])
        self.assertFalse(d["raster_quantitativo_baixado"])
        self.assertFalse(d["apto_estimativa_vazao"])
        a = Abridor(XML, "application/xml")
        with self.assertRaises(PermissionError):
            consultar_jrc_wmts(abridor=a)
        r = consultar_jrc_wmts(executar=True, abridor=a, instante=NOW)
        self.assertEqual(r["dados"]["quantidade_camadas"], 1)
        self.assertEqual(len(a.calls), 1)

    def test_jrc_xml_anomalo_bloqueado(self):
        for raw in (b"<html></html>", b"", b"<Capabilities></Capabilities>"):
            with self.assertRaises(ErroRasterCatalogo):
                normalizar_jrc_wmts(raw, coletado_em="2026-10-21T16:00:00Z")


if __name__ == "__main__":
    unittest.main()
