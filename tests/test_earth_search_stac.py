"""Testes STAC 100% sintéticos: transporte injetado, nenhuma chamada à AWS."""
import copy
import json
import unittest
from datetime import datetime, timezone
from nivon.earth_search_stac import ErroSTAC, consultar_cenas, normalizar_busca, planejar_busca

COL = "sentinel-2-c1-l2a"
BBOX = (-56.1, -13.1, -56.0, -13.0)
NOW = datetime(2026, 10, 21, 16, tzinfo=timezone.utc)


def obj():
    return {"type": "FeatureCollection",
            "features": [{
                "type": "Feature", "id": "S2_EXEMPLO_NAO_REAL",
                "collection": COL,
                "properties": {"datetime": "2026-10-20T14:30:00Z", "eo:cloud_cover": 12.1},
                "bbox": [-56.2, -13.2, -55.8, -12.8],
                "assets": {"red": {"href": "https://example.invalid/red.tif"},
                           "nir08": {"href": "https://example.invalid/nir.tif"}},
            }],
            "links": [{"rel": "self", "href": "https://example.invalid"}]}


def parse(data=None, **overrides):
    args = dict(bbox=BBOX, inicio="2026-10-19", fim="2026-10-21",
                colecao=COL, limite=10,
                coletado_em="2026-10-21T12:00:00-04:00")
    args.update(overrides)
    return normalizar_busca(json.dumps(data if data is not None else obj()).encode(), **args)


class Response:
    status = 200
    headers = {"Content-Type": "application/geo+json"}
    def __init__(self, url, body): self.url, self.body = url, body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def geturl(self): return self.url
    def read(self, n): return self.body[:n]


class Abridor:
    def __init__(self, body): self.body=body; self.urls=[]
    def open(self, req, timeout):
        self.urls.append(req.full_url)
        return Response(req.full_url, self.body)


class TestSTAC(unittest.TestCase):
    def test_plan_can_allow_only_small_bbox_recent_range(self):
        url = planejar_busca(bbox=BBOX, inicio="2026-10-19", fim="2026-10-21")
        self.assertTrue(url.startswith("https://earth-search.aws.element84.com/v1/search?"))
        self.assertIn("sentinel-2-c1-l2a", url)
        self.assertIn("limit=10", url)
        for bb in [(-180, -20, 180, 20), (-56, -13, -57, -12), (-56, -13, float("nan"), -12)]:
            with self.subTest(bb=bb), self.assertRaises(ErroSTAC):
                planejar_busca(bbox=bb, inicio="2026-10-19", fim="2026-10-21")
        with self.assertRaises(ErroSTAC):
            planejar_busca(bbox=BBOX, inicio="2026-01-01", fim="2026-10-21")
        with self.assertRaises(ErroSTAC):
            planejar_busca(bbox=BBOX, inicio="2026-10-19", fim="2026-10-21", colecao="malicious")
        with self.assertRaises(ErroSTAC):
            planejar_busca(bbox=BBOX, inicio="2026-10-19", fim="2026-10-21", limite=1000)

    def test_scene_metadata_distinct_from_pixel_data(self):
        out = parse()
        self.assertEqual(out["total_pagina"], 1)
        self.assertEqual(out["itens"][0]["data_referencia"], "2026-10-20")
        self.assertEqual(out["itens"][0]["cobertura_nuvens_pct"], 12.1)
        self.assertEqual(out["itens"][0]["nomes_bandas_e_assets"], ["nir08", "red"])
        self.assertEqual(out["itens"][0]["coleta"], "2026-10-21T16:00:00+00:00")
        self.assertIsNone(out["itens"][0]["publicacao"])
        self.assertFalse(out["dados_raster_baixados"])
        self.assertFalse(out["apto_publicacao"])
        self.assertNotIn("href", json.dumps(out))

    def test_request_exactly_once_and_default_deny(self):
        abridor = Abridor(json.dumps(obj()).encode())
        with self.assertRaises(PermissionError):
            consultar_cenas(bbox=BBOX, inicio="2026-10-19", fim="2026-10-21", abridor=abridor)
        self.assertEqual(abridor.urls, [])
        out = consultar_cenas(bbox=BBOX, inicio="2026-10-19", fim="2026-10-21",
                             executar=True, abridor=abridor, instante=NOW)
        self.assertEqual(len(abridor.urls), 1)
        self.assertEqual(out["dados"]["total_pagina"], 1)
        self.assertEqual(len(out["aquisição"]["sha256"]), 64)

    def test_collection_date_and_cloud_are_checked(self):
        for field, value in [
            ("collection", "landsat-c2-l2"),
            ("properties", {"datetime": "2025-10-20T14:30:00Z"}),
            ("properties", {"datetime": "2026-10-20T14:30:00Z", "eo:cloud_cover": 120}),
        ]:
            d = obj()
            d["features"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ErroSTAC):
                parse(d)

    def test_cursor_present_never_auto_visited(self):
        d = obj()
        d["links"].append({"rel": "next", "href": "https://malicious.invalid/next"})
        out = parse(d)
        self.assertTrue(out["tem_proxima_pagina"])
        self.assertFalse(out["historico_completo"])

    def test_duplicate_or_excess_scenes_fail_closed(self):
        d = obj(); d["features"].append(copy.deepcopy(d["features"][0]))
        with self.assertRaises(ErroSTAC): parse(d)
        with self.assertRaises(ErroSTAC): parse(d, limite=1)

    def test_invalid_json_missing_features_and_duplicate_keys(self):
        for data in (b"[]", b"{}", b'{"type":"FeatureCollection","type":"FeatureCollection"}', b""):
            with self.assertRaises(ErroSTAC):
                normalizar_busca(data, bbox=BBOX, inicio="2026-10-19",
                                 fim="2026-10-21", colecao=COL, limite=10,
                                 coletado_em="2026-10-21T12:00:00-04:00")


if __name__ == "__main__":
    unittest.main()
