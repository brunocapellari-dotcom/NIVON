"""BCB SICOR/MDCR OData v2: testes offline sem rede."""
import json
import unittest
from datetime import datetime, timezone
from nivon.bcb_sicor_mdcr import (
    ENTIDADES, ErroSicor, consultar_sicor, normalizar_sicor, planejar_sicor,
)

T = "2026-10-21T19:00:00+00:00"

class FakeResponse:
    status = 200
    def __init__(self, url, obj, mime="application/json"):
        self.url, self.headers = url, {"Content-Type": mime}
        self.data = json.dumps(obj).encode()
    def geturl(self): return self.url
    def read(self, n): return self.data[:n]
    def __enter__(self): return self
    def __exit__(self, *a): return False

class FakeOpener:
    def __init__(self, response): self.response, self.calls = response, 0
    def open(self, req, timeout=15):
        self.calls += 1
        return self.response

class BcbSicorTest(unittest.TestCase):
    def test_necessita_opt_in_real(self):
        for entity in ENTIDADES:
            with self.subTest(entity=entity), self.assertRaises(PermissionError):
                consultar_sicor(entidade=entity)

    def test_endpoint_sicor_v2_unico(self):
        for entity in ENTIDADES:
            p = planejar_sicor(entidade=entity, limite=2)
            self.assertIn("/SICOR/versao/v2/odata/" + entity, p["url"])
            self.assertIn("%24top=2", p["url"])
            self.assertIn("%24format=json", p["url"])
            self.assertNotIn("filter", p["url"])

    def test_rejeita_entidades_invalidas(self):
        for entity in ("../", "Municipio", "CEPEA", "CusteioMunicipioProduto?$skip=100"):
            with self.assertRaises(ErroSicor):
                planejar_sicor(entidade=entity)
        for limit in (0, 26, "2", True, -1):
            with self.assertRaises(ErroSicor):
                planejar_sicor(limite=limit)

    def test_parse_metadados_nao_totais(self):
        payload = json.dumps({"@odata.context": "$metadata#CusteioMunicipioProduto",
                              "value": [{"municipio": "Lucas do Rio Verde", "valor": 100},
                                        {"municipio": "Sorriso", "valor": 200}],
                              "@odata.nextLink": "https://invalid.example/continuar"}).encode()
        d = normalizar_sicor(payload, entidade="CusteioMunicipioProduto",
                             limite=2, coletado_em=T)
        self.assertEqual(d["registros_recebidos"], 2)
        self.assertEqual(d["campos_declarados"], ["municipio", "valor"])
        self.assertTrue(d["paginacao_bloqueada"])
        self.assertFalse(d["valores_monetarios_homologados"])
        self.assertFalse(d["persistido"])
        self.assertFalse(d["publicavel"])

    def test_realiza_exatamente_um_get_quando_explicito(self):
        p = planejar_sicor(entidade="RegiaoUF", limite=3)
        fake = FakeOpener(FakeResponse(p["url"], {"value": [{"a": 1}]}))
        d = consultar_sicor(entidade="RegiaoUF", limite=3, executar=True,
                            abridor=fake,
                            instante=datetime(2026, 10, 21, tzinfo=timezone.utc))
        self.assertEqual(fake.calls, 1)
        self.assertEqual(d["registros_recebidos"], 1)
        self.assertEqual(d["source_id"], "BCB")

    def test_redirecionamento_waf_e_tamanho(self):
        p = planejar_sicor()
        with self.assertRaises(ErroSicor):
            consultar_sicor(executar=True,
                abridor=FakeOpener(FakeResponse("https://attacker.example/", {"value": []})))
        with self.assertRaises(ErroSicor):
            consultar_sicor(executar=True,
                abridor=FakeOpener(FakeResponse(p["url"], {"value": []}, "text/html")))

    def test_schema_e_tempo(self):
        for raw in (b'{"value":[{},{}]}', b'{"value":{}}', b'[]',
                    b'{"value":[],"value":[]}', b'{}'):
            with self.assertRaises(ErroSicor):
                normalizar_sicor(raw, entidade="RegiaoUF", limite=1, coletado_em=T)
        with self.assertRaises(ErroSicor):
            normalizar_sicor(b'{"value":[]}', entidade="RegiaoUF", limite=1,
                             coletado_em="2026-10-21T19:00:00")
        d = normalizar_sicor(b'{"value":[]}', entidade="RegiaoUF",
                             limite=1, coletado_em=T)
        self.assertEqual(d["registros_recebidos"], 0)

if __name__ == "__main__":
    unittest.main()
