"""Regressão offline das fontes gratuitas. Nenhuma requisição em testes."""
import hashlib
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from nivon.fontes_abertas_lote import (
    CKAN, FONTES, MAX_BYTES, ErroFonteAberta, consultar, normalizar, planejar
)

T = "2026-10-21T13:00:00+00:00"

def payload(obj):
    return json.dumps(obj).encode()

class Resp:
    status = 200
    def __init__(self, url, obj, mime="application/json"):
        self.url = url
        self.data = payload(obj)
        self.headers = {"Content-Type": mime}
    def geturl(self):
        return self.url
    def read(self, size):
        return self.data[:size]
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

class Fake:
    def __init__(self, response):
        self.response = response
        self.calls = 0
    def open(self, request, timeout=15):
        self.calls += 1
        return self.response

class FontesAbertasTest(unittest.TestCase):
    def test_negar_rede_por_padrao_11_fontes(self):
        self.assertEqual(len(FONTES), 12)
        for fonte in FONTES:
            with self.subTest(fonte=fonte), self.assertRaises(PermissionError):
                consultar(fonte)

    def test_ckan_whitelist_e_sem_links_externos(self):
        for fonte, (host, slug) in CKAN.items():
            plano = planejar(fonte)
            self.assertIn(host, plano["url"])
            self.assertIn("package_show", plano["url"])
            doc = {"success": True, "result": {
                "name": slug, "license_id": "cc-by", "metadata_modified": T,
                "resources": [{"id": "1", "format": "CSV", "name": "arquivo",
                    "url": "https://example.org/private.csv"},
                    {"id": "2", "format": "ZIP", "url": "https://" + host + "/dados.csv"}]}}
            result = normalizar(payload(doc), fonte=fonte, coletado_em=T)
            self.assertEqual(result["total_recursos"], 2)
            self.assertIsNone(result["recursos"][0]["url_somente_referencia"])
            self.assertEqual(result["recursos"][1]["url_somente_referencia"],
                             "https://" + host + "/dados.csv")
            self.assertFalse(result["persistido"])
            self.assertFalse(result["publicavel"])

    def test_ckan_nao_aceitar_dataset_trocado(self):
        fonte = "MAPA_ZARC"
        with self.assertRaises(ErroFonteAberta):
            normalizar(payload({"success": True, "result": {"name": "outro",
                  "resources": []}}), fonte=fonte, coletado_em=T)

    def test_ckan_rejeita_id_duplicado(self):
        with self.assertRaises(ErroFonteAberta):
            normalizar(payload({"success": True, "result": {
                "name": CKAN["ANTT_CIOT"][1],
                "resources": [{"id": "1"}, {"id": "1"}]}}),
                fonte="ANTT_CIOT", coletado_em=T)

    def test_planejar_sem_chaves_expoe_apenas_exigencia(self):
        for f in ("FRED", "EIA", "NOAA_CDO", "USDA_NASS"):
            with self.subTest(fonte=f), self.assertRaises(PermissionError):
                planejar(f, ambiente={})
        self.assertTrue(planejar("FRED",
                         ambiente={"NIVON_FRED_API_KEY": "a"*32})["url"].startswith(
                            "https://api.stlouisfed.org/"))
        self.assertEqual(planejar("NOAA_CDO",
                          ambiente={"NIVON_NOAA_CDO_TOKEN": "a"*32})["headers"]["token"],
                         "a"*32)

    def test_preview_comtrade_tem_recorte_estrito(self):
        self.assertIn("cmdCode=1201", planejar("UN_COMTRADE_PREVIEW", ano=2025)["url"])
        for kwargs in ({"ano": None}, {"ano": "2025"}, {"ano": 2025, "hs": "0000"},
                       {"ano": 2025, "fluxo": "Q"}, {"ano": 2025, "reporter": -1}):
            with self.assertRaises(ErroFonteAberta):
                planejar("UN_COMTRADE_PREVIEW", **kwargs)
        dados = normalizar(payload({"data": [{"reporterCode": 76}]}),
                           fonte="UN_COMTRADE_PREVIEW", coletado_em=T)
        self.assertEqual(dados["linhas"], 1)
        self.assertFalse(dados["homologado"])

    def test_stac_sem_assets(self):
        o = normalizar(payload({"id": "sentinel-2-l2a", "type": "Collection", "license": "other"}),
                       fonte="COPERNICUS_STAC_CATALOG", coletado_em=T)
        self.assertEqual(o["colecoes"], ["sentinel-2-l2a"])
        self.assertFalse(o["persistido"])

    def test_transportes_mime_redirect_limitados(self):
        fonte = "MAPA_ZARC"
        url = planejar(fonte)["url"]
        corpo = {"success": True, "result": {"name": CKAN[fonte][1], "resources": []}}
        good = Fake(Resp(url, corpo))
        out = consultar(fonte, executar=True, abridor=good,
                       instante=datetime(2026, 10, 21, tzinfo=timezone.utc))
        self.assertEqual(out["total_recursos"], 0)
        self.assertEqual(good.calls, 1)
        with self.assertRaises(ErroFonteAberta):
            consultar(fonte, executar=True,
                     abridor=Fake(Resp("https://evil.example/", corpo)))
        with self.assertRaises(ErroFonteAberta):
            consultar(fonte, executar=True, abridor=Fake(Resp(url, corpo, "text/html")))

    def test_json_invalido_duplicado_fuso_limite(self):
        with self.assertRaises(ErroFonteAberta):
            normalizar(b'{"success":1,"success":1}', fonte="ANTT_CIOT", coletado_em=T)
        with self.assertRaises(ErroFonteAberta):
            normalizar(b'{}', fonte="ANTT_CIOT", coletado_em="2026-10-21T12:00:00")
        with self.assertRaises(ErroFonteAberta):
            normalizar(b"x" * (MAX_BYTES + 1), fonte="ANTT_CIOT", coletado_em=T)

    def test_nao_aceitar_fonte_arbitraria(self):
        with self.assertRaises(ErroFonteAberta):
            planejar("https://127.0.0.1/")
        with self.assertRaises(ErroFonteAberta):
            normalizar(b"{}", fonte="DESCONHECIDA", coletado_em=T)

if __name__ == "__main__":
    unittest.main()
