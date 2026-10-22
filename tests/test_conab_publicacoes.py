"""CONAB: verificacao deterministica de novas edicoes publicadas."""
from datetime import date
import unittest
from nivon.conab_publicacoes import (
    CatalogoConabInvalido, selecionar_publicacoes, normalizar_publicacao,
)
HOJE=date(2026,10,21)
URL="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/"
def row(safra,n,pub):
    return {"safra":safra,"levantamento":n,"data_publicacao":pub,
            "url":URL+"boletim.xlsx"}
class PublicacoesTest(unittest.TestCase):
    def setUp(self):
        self.c=[
            row("2026/27",2,"2026-11-13"),
            row("2025/26",12,"2026-09-15"),
            row("2026/27",1,"2026-10-15"),
            row("2025/26",11,"2026-08-13"),
            row("2024/25",12,"2025-09-18"),
        ]
    def test_seleciona_somente_publicados(self):
        x=selecionar_publicacoes(self.c,hoje=HOJE)
        self.assertEqual([(r["safra"],r["levantamento"]) for r in x],
                         [("2026/27",1),("2025/26",12)])
    def test_avanca_com_nova_publicacao(self):
        x=selecionar_publicacoes(self.c,hoje=date(2026,11,13))
        self.assertEqual([(r["safra"],r["levantamento"]) for r in x],
                         [("2026/27",2),("2026/27",1)])
    def test_nao_antecipa_edicao_futura(self):
        self.assertEqual(selecionar_publicacoes(self.c,hoje=date(2026,10,14))[0]["safra"],"2025/26")
    def test_backfill_limitado(self):
        self.assertEqual(len(selecionar_publicacoes(self.c,hoje=HOJE,limite=4)),4)
    def test_conflito_mesmo_numero(self):
        with self.assertRaises(CatalogoConabInvalido):
            selecionar_publicacoes([row("2026/27",1,"2026-10-15"),
                                    row("2026/27",1,"2026-10-16")],hoje=HOJE)
    def test_duplicata_exata(self):
        r=row("2026/27",1,"2026-10-15")
        self.assertEqual(len(selecionar_publicacoes([r,r],hoje=HOJE)),1)
    def test_url_e_data_invalidas(self):
        r=row("2026/27",1,"2026-10-15")
        r["url"]="http://www.gov.br/conab/test.xlsx"
        self.assertIsNone(normalizar_publicacao(r,HOJE))
        self.assertIsNone(normalizar_publicacao(row("2026/28",1,"2026-10-15"),HOJE))
        self.assertIsNone(normalizar_publicacao(row("2026/27",1,"2040-10-15"),HOJE))
    def test_recusa_catalogo_vazio(self):
        with self.assertRaises(CatalogoConabInvalido):
            selecionar_publicacoes([],hoje=HOJE)
    def test_limite_controlado(self):
        for n in (0,13,True):
            with self.subTest(n=n),self.assertRaises(ValueError):
                selecionar_publicacoes(self.c,hoje=HOJE,limite=n)
if __name__=="__main__":
    unittest.main()
