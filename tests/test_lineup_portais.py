import unittest
from nivon.lineup_portais import extrair_lineup_portal, ErroPortal

AGORA = "2026-10-19T16:00:00-03:00"
ITAQUI = "https://www.portodoitaqui.com.br/porto-agora/navios"
ARATU = "https://www.codeba.gov.br/eficiente/sites/portalcodeba/pt-br/porto_aratu.php?secao=tportos_aratu"


class TestLineupPortais(unittest.TestCase):
    def itaqui(self, data="19/10/26"):
        return (
            "<h3>Navios Atracados</h3>"
            "<table><tr><th>Berço</th><th>IMO</th><th>Navio</th><th>Carga</th>"
            "<th>Qtd.Carga</th><th>Ultima Atualização</th></tr>"
            "<tr><td>B104</td><td>9416393</td><td>HONESTY</td>"
            "<td>DIESEL</td><td>45.583</td><td>"+data+"</td></tr></table>"
            "<h3>Navios Fundeados</h3>"
            "<table><tr><th>IMO</th><th>Navio</th><th>Carga</th>"
            "<th>Qtd.Carga</th><th>Ultima Atualizacao</th></tr>"
            "<tr><td>9452543</td><td>THEMIS</td><td>SOJA</td>"
            "<td>50.000</td><td>"+data+"</td></tr></table>"
        )

    def codeba(self):
        return (
            "<h3>PROGRAMAÇÃO DE NAVIOS - ESPERADOS</h3>"
            "<table><tr><th>Navio</th><th>DUV</th><th>ETA</th>"
            "<th>Carga / Tipo de Serviço</th><th>Qtd Carga Prev</th></tr>"
            "<tr><td>FEDERAL FREEDOM</td><td>488752026</td>"
            "<td>19/10/2026 13:00</td><td>FERT KCL GR / MOP</td>"
            "<td>29870000</td></tr></table>"
        )

    def test_itaqui_tres_estados_sem_converter_quantidade(self):
        r=extrair_lineup_portal(self.itaqui(),porto_id="ITAQUI",fonte_url=ITAQUI,coletado_em=AGORA)
        self.assertEqual(len(r["registros"]),2)
        self.assertEqual({x["situacao"] for x in r["registros"]},{"ATRACADO","AO_LARGO"})
        self.assertEqual(r["registros"][0]["quantidade_fonte_texto"],"45.583")
        self.assertIsNone(r["registros"][0]["toneladas_programadas"])
        self.assertFalse(r["registros"][0]["apto_briefing"])

    def test_itaqui_stale_nao_virar_lineup_atual(self):
        r=extrair_lineup_portal(self.itaqui("07/05/25"),porto_id="ITAQUI",fonte_url=ITAQUI,coletado_em=AGORA)
        self.assertTrue(all(not x["linha_recente_por_data"] for x in r["registros"]))
        self.assertTrue(all(x["bloqueio"]=="ATUALIZACAO_AUSENTE_OU_ANTIGA" for x in r["registros"]))

    def test_itaqui_data_futura_rejeitada(self):
        with self.assertRaises(ErroPortal):
            extrair_lineup_portal(self.itaqui("20/10/26"),porto_id="ITAQUI",fonte_url=ITAQUI,coletado_em=AGORA)

    def test_codeba_nao_inventa_data_publicacao_nem_toneladas(self):
        x=extrair_lineup_portal(self.codeba(),porto_id="ARATU",fonte_url=ARATU,coletado_em=AGORA)
        self.assertEqual(x["registros"][0]["duv"],"488752026")
        self.assertEqual(x["registros"][0]["situacao"],"ESPERADO")
        self.assertIsNone(x["registros"][0]["publicado_em"])
        self.assertEqual(x["registros"][0]["quantidade_fonte_texto"],"29870000")
        self.assertFalse(x["registros"][0]["apto_briefing"])

    def test_codeba_tabela_sem_navio_nao_e_zero_homologado(self):
        with self.assertRaises(ErroPortal):
            extrair_lineup_portal("<h3>Outros</h3><table><tr><th>Navio</th></tr></table>",
                                 porto_id="ARATU",fonte_url=ARATU,coletado_em=AGORA)

    def test_nao_pode_trocar_secao_codeba(self):
        with self.assertRaises(ErroPortal):
            extrair_lineup_portal(self.codeba(),porto_id="ARATU",
                fonte_url=ARATU.replace("tportos_aratu","tportos_salvador"),coletado_em=AGORA)

    def test_coleta_sem_fuso_nao_permitida(self):
        with self.assertRaises(ValueError):
            extrair_lineup_portal(self.itaqui(),porto_id="ITAQUI",fonte_url=ITAQUI,
                                 coletado_em="2026-10-19T16:00:00")

    def test_ausencia_real_de_programacao_nao_cria_navios(self):
        r=extrair_lineup_portal(
            "<h3>PROGRAMAÇÃO DE NAVIOS - ESPERADOS</h3><table>"
            "<tr><th>Navio</th><th>DUV</th><th>Carga / Tipo de Serviço</th>"
            "<th>Qtd Carga Prev</th></tr></table>Sem novas programações.",
            porto_id="ARATU",fonte_url=ARATU,coletado_em=AGORA)
        self.assertEqual(r["registros"],[])
        self.assertEqual(r["status"],"EXTRAIDO_NAO_HOMOLOGADO_NAO_PUBLICAVEL")


if __name__=="__main__":
    unittest.main()
