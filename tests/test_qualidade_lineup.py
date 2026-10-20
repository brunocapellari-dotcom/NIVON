import unittest
from datetime import datetime
from nivon.qualidade_lineup import montar_painel_lineup, ErroQualidadeLineup

AGORA="2026-10-19T20:00:00-03:00"


class TestQualidadeLineup(unittest.TestCase):
    def licenca(self):
        return {"CDP":{"status":"APROVADA","evidencia_id":"SINTETICO_TESTE",
                       "operacoes":["LEITURA","COLETA","PUBLICACAO_DERIVADA"]}}

    def linha(self, **changes):
        r={"fonte_id":"CDP","porto_id":"SANTAREM","produto":"SOJA",
           "situacao":"PROGRAMADO","duv":"DUV-1",
           "publicado_em":"2026-10-19T10:00:00-03:00",
           "coletado_em":"2026-10-19T11:00:00-03:00",
           "referencia_em":"2026-10-19T09:00:00-03:00",
           "fonte_url":"https://www.cdp.com.br/programacao-de-navios-do-porto-de-santarem/",
           "classe_evidencia":"LINEUP_INFORMADO", "apto_briefing":True}
        r.update(changes)
        return r

    def resultado(self,*registros, licenca=None):
        return montar_painel_lineup(list(registros),
                                   self.licenca() if licenca is None else licenca,
                                   gerado_em=AGORA)

    def test_lineup_um_status_uma_linha(self):
        r=self.resultado(self.linha())
        self.assertEqual(len(r["painel"]),1)
        self.assertEqual(r["painel"][0]["status_informados"],{"PROGRAMADO":1})
        self.assertEqual(r["painel"][0]["escalas_distintas"],1)
        self.assertEqual(r["indicadores_briefing"][0]["secao"],"PORTOS")

    def test_repeticoes_mesmo_navio_nao_contam_duas_vezes(self):
        r=self.resultado(self.linha(),self.linha())
        self.assertEqual(r["painel"][0]["escalas_distintas"],1)
        self.assertEqual(len(r["rejeicoes"]),1)

    def test_navio_2022_nao_consta_em_2026(self):
        r=self.resultado(self.linha(
            publicado_em="2022-12-07T10:00:00-03:00",
            referencia_em="2022-12-07T09:00:00-03:00",
            coletado_em="2026-10-19T11:00:00-03:00"))
        self.assertEqual(r["painel"],[])
        self.assertEqual(r["indicadores_briefing"],[])
        self.assertIn("antiga",r["rejeicoes"][0]["motivo"])

    def test_pagina_republicada_hoje_linha_velha_nao_passa(self):
        r=self.resultado(self.linha(
            referencia_em="2025-12-18T09:00:00-03:00"))
        self.assertEqual(r["painel"],[])

    def test_sem_hora_publicacao_nao_vira_noticia_recente(self):
        r=self.resultado(self.linha(publicado_em=None))
        self.assertEqual(r["painel"],[])
        self.assertEqual(len(r["rejeicoes"]),1)

    def test_sem_licenca_nao_publica(self):
        l=self.licenca()
        l["CDP"]["status"]="REVIEW"
        r=self.resultado(self.linha(),licenca=l)
        self.assertEqual(r["indicadores_briefing"],[])

    def test_volumes_so_com_lote_e_unidade(self):
        r=self.resultado(self.linha(toneladas_programadas=50000,lote_id="L1",
                                    unidade_confirmada="T"))
        self.assertEqual(r["painel"][0]["toneladas_programadas_com_lote"],50000)
        fail=self.resultado(self.linha(toneladas_programadas=50000,
                                     unidade_confirmada="NAO_CONFIRMADA"))
        self.assertEqual(fail["painel"],[])
        self.assertTrue(fail["rejeicoes"])

    def test_nao_promover_operacao_como_realizada(self):
        r=self.resultado(self.linha(situacao="CONCLUIDO"))
        self.assertEqual(r["painel"],[])

    def test_nao_afirma_zero_navios_quando_nao_ha_dados(self):
        r=self.resultado()
        self.assertEqual(r["painel"],[])
        self.assertIn("não validada",r["observacao"])

    def test_coleta_no_futuro_bloqueada(self):
        r=self.resultado(self.linha(coletado_em="2026-10-20T14:00:00-03:00"))
        self.assertEqual(r["painel"],[])

if __name__=="__main__":
    unittest.main()
