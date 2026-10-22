import unittest
from datetime import date
from nivon.conab_publicacoes import selecionar_publicacoes

ROOT="https://www.gov.br/conab/test.xlsx"
def rel(s,n,d):
    return {"safra":s,"levantamento":n,"data_publicacao":d,"url":ROOT}

class TestSelector(unittest.TestCase):
    def test_only_published(self):
        releases=[rel("2026/27",2,"2026-11-13"),
                  rel("2026/27",1,"2026-10-15"),
                  rel("2025/26",12,"2026-09-15")]
        result=selecionar_publicacoes(releases,hoje=date(2026,10,21))
        self.assertEqual([(r["safra"],r["levantamento"]) for r in result],
                         [("2026/27",1),("2025/26",12)])
        later=selecionar_publicacoes(releases,hoje=date(2026,11,13))
        self.assertEqual(later[0]["levantamento"],2)

if __name__=="__main__":
    unittest.main()
