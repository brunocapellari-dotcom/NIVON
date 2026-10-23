"""Verificação offline do descobridor de arquivos MDF-e da ANTT."""
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
import unittest

from nivon.antt_mdfe_catalogo import (
    QUERIES, API, ErroCatalogoANTT, _safe_csv, _request, descobrir, inspecionar,
)

UUID = "12345678-1234-1234-1234-123456789012"
URL = f"https://dados.antt.gov.br/dataset/x/resource/{UUID}/download/matriz_mdfe.csv"

class FakeResponse:
    status = 200
    def __init__(self, url, body, mime="application/json", status=200):
        self.url, self.body, self.status = url, body, status
        self.headers = {"Content-Type": mime}
    def geturl(self): return self.url
    def read(self, size): return self.body[:size]
    def __enter__(self): return self
    def __exit__(self, *args): return False

class FakeOpener:
    def __init__(self, dataset=None):
        self.calls = []
        self.dataset = dataset or []
    def open(self, req, timeout):
        self.calls.append(req.full_url)
        parsed = urlsplit(req.full_url)
        assert parsed.hostname == "dados.antt.gov.br"
        assert parse_qs(parsed.query)["q"][0] in QUERIES
        assert timeout == 20
        body = json.dumps({"success": True, "result": {
            "count": len(self.dataset), "results": self.dataset}}).encode()
        return FakeResponse(req.full_url, body)

def obj(fmt="CSV", title="Transporte MDF-e Origem Destino", url=URL):
    return {"id": UUID, "title": title, "notes": "Painel de manifesto eletrônico",
            "metadata_modified": "2026-10-22T12:00:00",
            "license_id": "cc-by", "resources": [{"format": fmt, "url": url}]}

class TestCatalogoANTT(unittest.TestCase):
    def test_candidato_csv_ponto_nao_coleta(self):
        d = inspecionar([obj(), obj()])
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["classificacao"], "MDFE_COM_CSV_CANDIDATO_NAO_HOMOLOGADO")
        self.assertEqual(d[0]["recursos_csv_oficiais"], [URL])

    def test_nao_classificar_ferrovia_ou_rntrc_como_mdfe(self):
        d = inspecionar([obj(title="Produção Ferroviária Origem Destino")])
        self.assertEqual(d[0]["classificacao"], "MDFE_COM_CSV_CANDIDATO_NAO_HOMOLOGADO")
        # O texto 'manifesto eletrônico' no metadado impõe somente status CANDIDATO, nunca homologação de volume.
        self.assertEqual(d[0]["recursos_csv_oficiais"], [URL])
        d2 = inspecionar([{"id": UUID, "title": "Produção Ferroviária Origem Destino",
                           "notes": "volume nas ferrovias", "resources": [{"format": "CSV", "url": URL}]}])
        self.assertEqual(d2[0]["classificacao"], "CATALOGO_SEM_PROVA_MDFE")

    def test_whitelist_urls(self):
        self.assertTrue(_safe_csv(URL))
        for candidate in [
            "https://app.powerbi.com/view?r=teste",
            "https://dados.antt.gov.br.evil.test/dataset/x/resource/y/download/x.csv",
            "http://dados.antt.gov.br/dataset/x/resource/y/download/x.csv",
            URL+"?redirect=https://evil.test",
            "https://dados.antt.gov.br/dataset/x",
            "https://dados.antt.gov.br/dataset/x/resource/y/download/x.xlsx",
        ]:
            self.assertFalse(_safe_csv(candidate))

    def test_consultas_sem_paginacao_oculta(self):
        client = FakeOpener([obj()])
        result = descobrir(opener=client, agora=datetime(2026,10,22,tzinfo=timezone.utc))
        self.assertEqual(len(client.calls), 4)
        self.assertEqual(result["status"], "CANDIDATOS_PARA_HOMOLOGACAO")
        self.assertEqual(result["datasets_unicos"], 1)
        self.assertEqual(result["candidatos_csv_mdfe"], 1)
        self.assertTrue(result["esgotou_catalogo"])

    def test_termo_invalido_bloqueado(self):
        with self.assertRaises(ErroCatalogoANTT):
            _request("'; DROP TABLE produtos", FakeOpener())

if __name__ == "__main__":
    unittest.main()
