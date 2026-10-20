import unittest
from nivon.lineup_cdp_santarem import interpretar_santarem,ErroCDP,URL_SANTAREM


class TestCDPSantarem(unittest.TestCase):
    def html(self, *,at="14/10/2026",carga="MILHO<br>FARELO DE SOJA",
             quant="12.500<br>7.000",rid="36"):
        return ('<h3>BERÇO 101 PÍER EXTERNO</h3>'
                '<table><tr><th>wdt_ID</th><th>NAVIO</th><th>CARGA</th>'
                '<th>QUANTIDADE(T)</th><th>CHEGADA</th><th>ATRACAÇÃO</th>'
                '<th>DESATRACAÇÃO</th></tr><tr>'
                f'<td>{rid}</td><td>HANZE GENUA</td><td>{carga}</td><td>{quant}</td>'
                f'<td></td><td>{at}</td><td></td></tr></table>')

    def analisar(self,html):
        return interpretar_santarem(html,coletado_em="2026-10-19T16:00:00-03:00",
                                   fonte_url=URL_SANTAREM)

    def test_dois_produtos_um_registro_nao_dois_navios(self):
        x=self.analisar(self.html())
        self.assertEqual(x["linhas_origem"],1)
        self.assertEqual(len(x["registros"]),2)
        self.assertEqual([r["produto_original"] for r in x["registros"]],
                         ["MILHO","FARELO DE SOJA"])
        self.assertEqual([r["toneladas_na_pagina"] for r in x["registros"]],[12500,7000])
        self.assertTrue(all(r["duv"] is None for r in x["registros"]))
        self.assertTrue(all(not r["apto_briefing"] for r in x["registros"]))

    def test_registro_2022_nao_e_situacao_atual(self):
        x=self.analisar(self.html(at="18/12/2022"))
        self.assertEqual(x["linhas_antigas_ou_sem_data"],1)
        self.assertTrue(x["registros"][0]["linha_antiga_ou_sem_referencia"])

    def test_tabela_com_um_produto(self):
        x=self.analisar(self.html(carga="UREIA",quant="25.000"))
        self.assertEqual(len(x["registros"]),1)
        self.assertEqual(x["registros"][0]["toneladas_na_pagina"],25000)

    def test_quantidade_incompativel_nao_adivinha(self):
        with self.assertRaises(ErroCDP):
            self.analisar(self.html(carga="MILHO<br>FARELO",quant="12500"))

    def test_data_invalida_nao_aceita(self):
        with self.assertRaises(ErroCDP):
            self.analisar(self.html(at="32/13/2026"))

    def test_dupla_wdt_mesma_tabela_nao_conta_duas(self):
        h=self.html()
        h=h.replace("</table>","<tr><td>36</td><td>OUTRO</td><td>MILHO</td>"
                    "<td>1.000</td><td></td><td>14/10/2026</td><td></td></tr></table>")
        with self.assertRaises(ErroCDP):
            self.analisar(h)

    def test_sem_novidades_nao_equivale_zero_navios(self):
        with self.assertRaises(ErroCDP):
            self.analisar("<table><tr><th>NAVIO</th></tr></table>")

    def test_url_alheia_nao_aceita(self):
        with self.assertRaises(ErroCDP):
            interpretar_santarem(self.html(),coletado_em="2026-10-19T16:00:00-03:00",
                               fonte_url="https://example.com/programacao")

if __name__=="__main__":
    unittest.main()
