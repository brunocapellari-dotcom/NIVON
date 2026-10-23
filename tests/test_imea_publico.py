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
    def test_same_id_different_chains_no_collision(self):
        soja=normalize(quote(cadeia="soja"))
        milho=normalize(quote(cadeia="milho"))
        self.assertNotEqual(soja["source_key"],milho["source_key"])

    def test_freight_and_price_have_distinct_identity(self):
        preco=normalize(quote(indicador="Preço soja disponível"))
        frete=normalize(quote(indicador="Preço Frete rodoviário",unidade="R$/t"))
        self.assertEqual(preco["indicator_kind"],"PRECO")
        self.assertEqual(frete["indicator_kind"],"FRETE")
        self.assertNotEqual(preco["source_key"],frete["source_key"])

    def test_reject_future_invalid_crop_and_wrong_freight_unit(self):
        from datetime import datetime
        for invalid in (quote(data_publicacao=datetime(2099,1,1)),
                        quote(safra="qualquer"),
                        quote(indicador="Frete rodoviário",unidade="R$/sc")):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                normalize(invalid)

    def test_different_publication_creates_distinct_identity(self):
        a=normalize(quote())
        b=normalize(quote(data_publicacao=datetime(2026,10,22,18,0)))
        self.assertNotEqual(a["source_key"],b["source_key"])
        self.assertEqual(a["version_hash"],b["version_hash"])

    def test_freight_stays_distinct(self):
        a=normalize(quote(indicador="Preço disponível do Frete de Grãos",
                          unidade="R$/t",valor=240))
        self.assertEqual(a["unit"],"R$/t")
        self.assertIsNone(a["reference_date"])

if __name__=="__main__":
    unittest.main()
