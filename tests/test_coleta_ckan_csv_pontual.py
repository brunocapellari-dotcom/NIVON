"""Testes de duas chamadas pontuais CKAN -> um CSV oficial, sem rede."""
import json
import unittest
from datetime import datetime, timezone

from nivon.coleta_ckan_csv_pontual import (
    coletar_amostra_csv, ErroCSVCKAN
)
from nivon.fontes_abertas_lote import planejar, CKAN

RID = "139e5a60-1f43-4cc8-aeab-a35dbbf816c0"
DT = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
FONTE = "MAPA_ZARC"
HOST = CKAN[FONTE][0]
CATALOGO_URL = planejar(FONTE)["url"]
CSV_URL = ("https://" + HOST + "/dataset/dados-abertos/"
           "resource/" + RID + "/download/safra.csv")
CSV = b"municipio;risco\n5105259;20\n"

class Resp:
    def __init__(self, url, data, mime):
        self.url = url
        self.raw = data
        self.status = 200
        self.headers = {"Content-Type": mime}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url
    def read(self, tamanho):
        return self.raw[:tamanho]

class Sequencia:
    def __init__(self, respostas):
        self.respostas = respostas
        self.pedidos = []
    def open(self, request, timeout=20):
        self.pedidos.append(request.full_url)
        if not self.respostas:
            raise AssertionError("houve chamada HTTP adicional")
        return self.respostas.pop(0)

def ckan(licenca="cc-by", url=CSV_URL):
    obj = {"success": True, "result": {
        "name": CKAN[FONTE][1], "license_id": licenca,
        "resources": [{"id": RID, "format": "CSV", "name": "ZARC",
                       "last_modified": "2026-10-01", "url": url}]}}
    return Resp(CATALOGO_URL, json.dumps(obj).encode(), "application/json")

class AmostrasCKANTest(unittest.TestCase):
    def test_rede_bloqueada_por_padrao(self):
        with self.assertRaises(PermissionError):
            coletar_amostra_csv(fonte=FONTE, recurso_id=RID)

    def test_uma_amostra_csv_com_hash_licenca_e_duas_chamadas(self):
        falso = Sequencia([ckan(), Resp(CSV_URL, CSV, "text/csv")])
        out = coletar_amostra_csv(
            fonte=FONTE, recurso_id=RID, executar=True,
            abridor=falso, instante=DT)
        self.assertEqual(falso.pedidos, [CATALOGO_URL, CSV_URL])
        self.assertEqual(out["linhas_amostra"], 1)
        self.assertEqual(out["chamadas_http"], 2)
        self.assertEqual(out["estado"], "CSV_RECEBIDO_SCHEMA_NAO_HOMOLOGADO")
        self.assertFalse(out["persistido"])
        self.assertFalse(out["homologado"])

    def test_bloqueio_licenca_nao_documentada_antes_download(self):
        falso = Sequencia([ckan(licenca="other")])
        with self.assertRaises(PermissionError):
            coletar_amostra_csv(fonte=FONTE, recurso_id=RID,
                                executar=True, abridor=falso, instante=DT)
        self.assertEqual(len(falso.pedidos), 1)

    def test_nao_seguir_host_externo(self):
        falso = Sequencia([ckan(url="https://not-official.example/safra.csv")])
        with self.assertRaises(ErroCSVCKAN):
            coletar_amostra_csv(fonte=FONTE, recurso_id=RID,
                                executar=True, abridor=falso, instante=DT)
        self.assertEqual(len(falso.pedidos), 1)

    def test_nao_baixar_outros_datasets(self):
        falso = Sequencia([])
        with self.assertRaises(PermissionError):
            coletar_amostra_csv(fonte="ANTT_RNTRC", recurso_id=RID,
                                executar=True, abridor=falso, instante=DT)
        self.assertEqual(falso.pedidos, [])

    def test_bloqueio_redirect_csv(self):
        falso = Sequencia([ckan(), Resp("https://other.example/dados.csv", CSV, "text/csv")])
        with self.assertRaises(ErroCSVCKAN):
            coletar_amostra_csv(fonte=FONTE, recurso_id=RID,
                                executar=True, abridor=falso, instante=DT)

    def test_bloqueio_html_csv(self):
        falso = Sequencia([ckan(), Resp(CSV_URL, b"<html>rejected</html>", "text/html")])
        with self.assertRaises(ErroCSVCKAN):
            coletar_amostra_csv(fonte=FONTE, recurso_id=RID,
                                executar=True, abridor=falso, instante=DT)

    def test_recurso_id_nunca_arbitrario(self):
        with self.assertRaises(ErroCSVCKAN):
            coletar_amostra_csv(fonte=FONTE, recurso_id="../../x",
                                executar=True, abridor=Sequencia([]), instante=DT)

if __name__ == "__main__":
    unittest.main()
