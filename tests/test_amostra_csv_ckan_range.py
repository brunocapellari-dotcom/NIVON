"""Amostragem Range CSV CKAN: sem rede; 200/206, cabeçalho e idempotência de prefixo."""
import json
import unittest
from datetime import datetime, timezone

from nivon.fontes_abertas_lote import CKAN, planejar
from nivon.amostra_csv_ckan_range import (
    ErroCSVCKAN, PREFIXO_MAX, _amostra_csv, consultar_prefixo_ckan
)

FONTE = "MAPA_ZARC"
RID = "139e5a60-1f43-4cc8-aeab-a35dbbf816c0"
CSV_URL = ("https://dados.agricultura.gov.br/dataset/"
           "6d3d141c-885e-41a4-ab7f-dc8ff323b96f/resource/" + RID
           + "/download/dados-abertos-tabua-de-risco-safra-2026-2027.csv")
DATA = datetime(2026, 10, 21, tzinfo=timezone.utc)

class Response:
    def __init__(self, url, status=200, raw=b"", mime="application/json", range_header=None):
        self.url, self.status, self.raw = url, status, raw
        self.headers = {"Content-Type": mime}
        if range_header is not None:
            self.headers["Content-Range"] = range_header
    def geturl(self): return self.url
    def read(self, n): return self.raw[:n]
    def __enter__(self): return self
    def __exit__(self, *args): return False

class Fake:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def open(self, req, timeout=20):
        self.calls.append((req.full_url, req.headers))
        if not self.responses:
            raise AssertionError("chamada HTTP indevida")
        return self.responses.pop(0)

def catalog(licence="cc-by"):
    obj = {"success": True, "result": {
        "name": CKAN[FONTE][1], "license_id": licence,
        "resources": [{"id": RID, "format": "CSV", "name": "Tabela ZARC",
                       "url": CSV_URL}]}}
    return Response(planejar(FONTE)["url"], raw=json.dumps(obj).encode())

class CSVRangeTest(unittest.TestCase):
    def test_ler_cabecalho_e_descartar_linha_cortada(self):
        x = _amostra_csv(b"a;b\n1;2\n3;4")
        self.assertEqual(x["colunas"], ["a", "b"])
        self.assertEqual(x["linhas_amostra_completas"], 1)

    def test_mock_206_duas_consultas_e_sem_full_sha(self):
        csv = b"municipio;cultura;risco\n5105259;SOJA;20\n5107925;MILHO;30"
        f = Fake([catalog(), Response(CSV_URL, status=206, raw=csv,
                        mime="text/csv", range_header="bytes 0-511/99999999")])
        res = consultar_prefixo_ckan(fonte=FONTE, recurso_id=RID,
              executar=True, abridor=f, instante=DATA, max_bytes=4096)
        self.assertEqual(len(f.calls), 2)
        self.assertEqual(res["linhas_amostra_completas"], 1)
        self.assertTrue(res["suporte_range_comprovado"])
        self.assertFalse(res["arquivo_completo"])
        self.assertIsNone(res["hash_do_arquivo_completo"])
        self.assertFalse(res["persistido"])
        self.assertFalse(res["publicavel"])
        self.assertEqual(res["colunas"], ["municipio","cultura","risco"])

    def test_sem_range_servidor_200_sem_download_completo(self):
        f = Fake([catalog(), Response(CSV_URL, status=200, raw=b"uf;valor\nMT;12\n", mime="text/csv")])
        res = consultar_prefixo_ckan(fonte=FONTE, recurso_id=RID,
            executar=True, abridor=f, instante=DATA, max_bytes=4096)
        self.assertEqual(res["http_status"], 200)
        self.assertFalse(res["suporte_range_comprovado"])

    def test_rede_default_off(self):
        with self.assertRaises(PermissionError):
            consultar_prefixo_ckan(fonte=FONTE, recurso_id=RID)
        with self.assertRaises(PermissionError):
            consultar_prefixo_ckan(fonte="CME_FUTUROS", recurso_id=RID, executar=True)

    def test_limites_e UUID(self):
        for lim in (0, 4095, PREFIXO_MAX+1, "1024", True):
            with self.assertRaises(ErroCSVCKAN):
                consultar_prefixo_ckan(fonte=FONTE,recurso_id=RID,
                                       max_bytes=lim,executar=True)
        with self.assertRaises(ErroCSVCKAN):
            consultar_prefixo_ckan(fonte=FONTE,recurso_id="../../",executar=True)

    def test_rejeitar_licenca_sem_get_csv(self):
        fake = Fake([catalog("other")])
        with self.assertRaises(PermissionError):
            consultar_prefixo_ckan(fonte=FONTE,recurso_id=RID,
                         executar=True,abridor=fake,instante=DATA,max_bytes=4096)
        self.assertEqual(len(fake.calls), 1)

    def test_range_malformado(self):
        fake = Fake([catalog(), Response(CSV_URL, status=206, raw=b"a\n1\n",
                         mime="text/csv", range_header="bytes 100-200/300")])
        with self.assertRaises(ErroCSVCKAN):
            consultar_prefixo_ckan(fonte=FONTE,recurso_id=RID,
                         executar=True,abridor=fake,instante=DATA,max_bytes=4096)

    def test_rejeitar_html_waf(self):
        fake = Fake([catalog(), Response(CSV_URL, status=200,
                         raw=b"<html>blocked</html>", mime="text/html")])
        with self.assertRaises(ErroCSVCKAN):
            consultar_prefixo_ckan(fonte=FONTE,recurso_id=RID,
                         executar=True,abridor=fake,instante=DATA,max_bytes=4096)

    def test_erro_cabecalho_duplicado(self):
        with self.assertRaises(ErroCSVCKAN):
            _amostra_csv(b"a;a\n1;2\n")

if __name__ == "__main__":
    unittest.main()
