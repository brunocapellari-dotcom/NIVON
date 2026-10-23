import unittest
from datetime import datetime
from nivon.imea_publico import normalize

def quote(**changes):
    row={"cadeia":"soja","indicador_id":"708192508838936580",
         "indicador":"Preço soja disponível compra","localidade":"Sorriso",
         "unidade":"R$/sc","valor":150.25,"safra":"26/27",
         "data_publicacao":datetime(2026,10,21,18,0)}
    row.update(changes)
    return row

class TestIMEA(unittest.TestCase):
    def test_preserve_large_id_and_published_date(self):
        r=normalize(quote())
        self.assertEqual(r["indicator_id"],"708192508838936580")
        self.assertEqual(r["value"],"150.25")
        self.assertEqual(r["published_at"],"2026-10-21T18:00:00")
        self.assertIsNone(r["reference_date"])
    def test_change_value_produces_revision_not_new_identity(self):
        a=normalize(quote())
        b=normalize(quote(valor=151))
        self.assertEqual(a["source_key"],b["source_key"])
        self.assertNotEqual(a["version_hash"],b["version_hash"])
    def test_zero_seeds_and_missing_data_are_blocked(self):
        for row in (quote(valor=0),quote(valor=float("nan")),
                    quote(indicador="SEMENTE SOJA BRANCA"),
                    quote(data_publicacao=None),quote(localidade="")):
            with self.subTest(row=row),self.assertRaises(ValueError):
                normalize(row)
    def test_freight_stays_distinct(self):
        a=normalize(quote(indicador="Preço disponível do Frete de Grãos",
                          unidade="R$/t",valor=240))
        self.assertEqual(a["unit"],"R$/t")
        self.assertIsNone(a["reference_date"])

if __name__=="__main__":
    unittest.main()
