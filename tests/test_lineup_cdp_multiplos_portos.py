import unittest

from nivon.lineup_cdp_santarem import (
    URLS_CDP, ErroCDP, interpretar_cdp, interpretar_santarem,
)


AGORA="2026-10-20T09:00:00-03:00"


def pagina(data="19/10/2026"):
    return (
        "<h3>BERÇO 101 CDP</h3><table><tr><th>wdt_ID</th><th>NAVIO</th>"
        "<th>CARGA</th><th>QUANTIDADE(T)</th><th>CHEGADA</th>"
        "<th>ATRACAÇÃO</th><th>DESATRACAÇÃO</th></tr>"
        "<tr><td>2</td><td>navio</td><td>carga</td><td></td><td></td>"
        "<td></td><td></td></tr>"
        "<tr><td>104</td><td>NAVIO SINTÉTICO</td><td>MILHO<br>FARELO DE SOJA</td>"
        "<td>30.000<br>9.000</td><td>"+data+"</td><td></td><td></td></tr></table>"
    )


class TestCDPMultiplosPortos(unittest.TestCase):
    def test_belem_com_placeholder_rejeitado(self):
        out=interpretar_cdp(pagina(),porto_id="BELEM",coletado_em=AGORA)
        self.assertEqual(out["porto_id"],"BELEM")
        self.assertEqual(out["linhas_origem"],1)
        self.assertEqual(len(out["registros"]),2)
        self.assertEqual(out["registros"][0]["toneladas_na_pagina"],30000.0)
        self.assertEqual(out["registros"][1]["toneladas_na_pagina"],9000.0)
        self.assertTrue(all(not x["apto_briefing"] for x in out["registros"]))
        self.assertTrue(all(x["duv"] is None for x in out["registros"]))

    def test_vila_do_conde_tem_identidade_separada(self):
        out=interpretar_cdp(pagina(),porto_id="BARCARENA_VILA_DO_CONDE",
                          coletado_em=AGORA)
        self.assertEqual(out["porto_id"],"BARCARENA_VILA_DO_CONDE")
        self.assertEqual(out["registros"][0]["fonte_url"],URLS_CDP["BARCARENA_VILA_DO_CONDE"])
        self.assertEqual(out["linhas_origem"],1)

    def test_cdp_santarem_mantem_interface_legada(self):
        out=interpretar_santarem(pagina(),coletado_em=AGORA)
        self.assertEqual(out["porto_id"],"SANTAREM")

    def test_placeholder_sozinho_nao_equivale_a_zero(self):
        page=pagina().replace(
            "<tr><td>104</td><td>NAVIO SINTÉTICO</td><td>MILHO<br>FARELO DE SOJA</td>"
            "<td>30.000<br>9.000</td><td>19/10/2026</td><td></td><td></td></tr>",""
        )
        with self.assertRaises(ErroCDP):
            interpretar_cdp(page,porto_id="BELEM",coletado_em=AGORA)

    def test_fonte_de_outro_porto_rejeitada(self):
        with self.assertRaises(ErroCDP):
            interpretar_cdp(pagina(),porto_id="BELEM",coletado_em=AGORA,
                          fonte_url=URLS_CDP["BARCARENA_VILA_DO_CONDE"])

    def test_registros_antigos_nao_podem_ser_publicados(self):
        out=interpretar_cdp(pagina("08/12/2022"),porto_id="BELEM",coletado_em=AGORA)
        self.assertEqual(out["linhas_antigas_ou_sem_data"],1)
        self.assertTrue(all(x["linha_antiga_ou_sem_referencia"] for x in out["registros"]))

    def test_porto_desconhecido_bloqueado(self):
        with self.assertRaises(ErroCDP):
            interpretar_cdp(pagina(),porto_id="MIRITITUBA",coletado_em=AGORA)


if __name__=="__main__":
    unittest.main()
