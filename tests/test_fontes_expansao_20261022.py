"""Cobertura offline dos 40 novos contratos e dos GETs pontuais."""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from nivon.fontes_expansao_20261022 import (
    FONTES_EXPANSAO, PLANOS_ESTRUTURADOS, ErroExpansao,
    listar_fontes, consultar, planejar,
)
from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas

T = datetime(2026, 10, 22, tzinfo=timezone.utc)


class Resp:
    status = 200
    headers = {"Content-Type": "application/json"}
    def __init__(self, url, obj):
        self.url = url
        self.raw = json.dumps(obj).encode()
    def geturl(self):
        return self.url
    def read(self, limit):
        return self.raw[:limit]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class Fake:
    def __init__(self, response):
        self.response = response
        self.calls = 0
    def open(self, request, timeout=20):
        self.calls += 1
        return self.response


class ExpansaoTest(unittest.TestCase):
    def test_cat_catalogo_40_rotas_10_bibliotecas(self):
        doc = carregar_catalogo()
        self.assertGreaterEqual(validar_catalogo(doc)["datasets"], 217)
        self.assertEqual(len(listar_fontes(doc)), 40)
        self.assertEqual(len(FONTES_EXPANSAO), 40)
        rotas = carregar_rotas()
        self.assertEqual(validar_rotas(rotas, doc)["rotas"], len(doc["datasets"]))

    def test_sempre_off_por_padrao(self):
        for f in FONTES_EXPANSAO:
            with self.subTest(f=f), self.assertRaises(PermissionError):
                consultar(f)

    def test_nao_inventar_endpoint(self):
        self.assertEqual(len(PLANOS_ESTRUTURADOS), 3)
        with self.assertRaises(PermissionError):
            planejar("ARG_SIO_GRANOS")
        with self.assertRaises(ErroExpansao):
            planejar("FONTE_DESCONHECIDA")

    def test_usda_exige_chave_e_nao_vaza_credencial_na_url(self):
        with self.assertRaises(PermissionError):
            planejar("USDA_MMN", ambiente={})
        p = planejar("USDA_MMN", ambiente={"NIVON_USDA_MMN_API_KEY": "A"*24})
        self.assertNotIn("AAAA", p["url"])
        self.assertTrue(p["headers"]["Authorization"].startswith("Basic "))

    def test_ckan_coleta_apenas_metadados(self):
        p = planejar("BR_CCEE_PLD")
        fake = Fake(Resp(p["url"], {"success": True, "result": {
            "name": "pld_horario", "resources": [{"id": "r1"}]}}))
        out = consultar("BR_CCEE_PLD", executar=True, abridor=fake, instante=T)
        self.assertEqual(fake.calls, 1)
        self.assertEqual(out["quantidade_itens_catalogo"], 1)
        self.assertFalse(out["publicavel"])
        self.assertFalse(out["persistido"])

    def test_bcra_coleta_metadados(self):
        p = planejar("ARG_BCRA")
        fake = Fake(Resp(p["url"], {"status": 200, "results": [{"id": 1}]}))
        out = consultar("ARG_BCRA", executar=True, abridor=fake, instante=T)
        self.assertEqual(out["quantidade_itens_catalogo"], 1)

    def test_resposta_incorreta_rejeitada(self):
        p = planejar("BR_CCEE_PLD")
        for doc in ({"success": False}, {"success": True, "result": {
            "name": "outro", "resources": []}}):
            with self.subTest(doc=doc), self.assertRaises(ErroExpansao):
                consultar("BR_CCEE_PLD", executar=True,
                         abridor=Fake(Resp(p["url"], doc)), instante=T)


if __name__ == "__main__":
    unittest.main()
