import copy
import unittest

from nivon.catalogo_fontes import carregar_catalogo
from nivon.lineup_nacional import carregar_escopo
from nivon.integracao_portos_briefing import (
    preparar_portos_para_briefing, montar_briefing_com_portos,
)


AGORA="2026-10-19T16:00:00-03:00"
URL="https://www.portodoitaqui.com.br/porto-agora/navios"


class TestIntegracaoPortosBriefing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogo_real=carregar_catalogo()
        cls.escopo_real=carregar_escopo()

    def licencas(self):
        return {"PORTO_ITAQUI":{
            "status":"APROVADA","evidencia_id":"SOMENTE_TESTE_FICTICIO",
            "operacoes":["LEITURA","COLETA","PUBLICACAO_DERIVADA"],
        }}

    def exemplo(self,**kw):
        r={"fonte_id":"PORTO_ITAQUI","porto_id":"ITAQUI","produto":"SOJA",
           "situacao":"PROGRAMADO","duv":"DUV-16","lote_id":"LOTE-1",
           "toneladas_programadas":42000.0,"unidade_confirmada":"T",
           "classe_evidencia":"LINEUP_INFORMADO","apto_briefing":True,
           "fonte_url":URL,"publicado_em":"2026-10-19T09:00:00-03:00",
           "referencia_em":"2026-10-19T10:00:00-03:00",
           "coletado_em":"2026-10-19T11:00:00-03:00"}
        r.update(kw)
        return r

    def simulados(self):
        cat=copy.deepcopy(self.catalogo_real)
        p=copy.deepcopy(self.escopo_real)
        d=next(x for x in cat["datasets"] if x["id"]=="LINEUP_ITAQUI")
        d["enabled"]=True
        d["collection_authorized"]=True
        d["commercial_redistribution_authorized"]=True
        port=next(x for x in p["ports"] if x["id"]=="ITAQUI")
        port["parser_homologated"]=True
        return cat,p

    def test_catalogo_real_bloqueia_mesmo_com_licenca_ficticia(self):
        x=preparar_portos_para_briefing(
            [self.exemplo()],self.licencas(),gerado_em=AGORA)
        self.assertEqual(x["indicadores"],[])
        self.assertEqual(x["status"],"DADOS_INDISPONIVEIS_OU_NAO_HOMOLOGADOS")
        self.assertIn("homologados",x["rejeicoes"][0]["motivo"])
        self.assertFalse(x["publicacao_executada"])

    def test_fluxo_sintetico_com_indicador_sem_enviar(self):
        cat,esc=self.simulados()
        b=montar_briefing_com_portos(
            noticias=[],fontes_noticias={},indicadores=[],
            registros_portuarios=[self.exemplo()],
            licencas_portuarias=self.licencas(),gerado_em=AGORA,
            catalogo=cat,escopo=esc,
        )
        self.assertEqual(b["status"],"PREPARADO_SEM_ENVIO")
        self.assertIn("ITAQUI — SOJA",b["texto"])
        self.assertIn("PROGRAMADO: 1",b["texto"])
        self.assertEqual(b["painel_portuario"][0]["escalas_distintas"],1)
        self.assertNotIn("0 navios",b["texto"])

    def test_pagina_antiga_nao_entra_mesmo_em_cenario_sintetico(self):
        cat,esc=self.simulados()
        b=montar_briefing_com_portos(
            noticias=[],fontes_noticias={},indicadores=[],
            registros_portuarios=[self.exemplo(
                referencia_em="2022-12-20T10:00:00-03:00")],
            licencas_portuarias=self.licencas(),
            gerado_em=AGORA,catalogo=cat,escopo=esc)
        self.assertEqual(b["painel_portuario"],[])
        self.assertNotIn("ITAQUI — SOJA",b["texto"])
        self.assertTrue(b["rejeicoes"])

    def test_parser_nunca_auto_homologa(self):
        cat,esc=self.simulados()
        b=preparar_portos_para_briefing(
            [self.exemplo(apto_briefing=False)],self.licencas(),
            gerado_em=AGORA,catalogo=cat,escopo=esc)
        self.assertEqual(b["indicadores"],[])
        self.assertTrue(b["rejeicoes"])

    def test_outra_fonte_nao_pode_fingir_ser_porto(self):
        cat,esc=self.simulados()
        b=preparar_portos_para_briefing(
            [self.exemplo(fonte_id="ANP")],self.licencas(),
            gerado_em=AGORA,catalogo=cat,escopo=esc)
        self.assertEqual(b["indicadores"],[])
        self.assertIn("associados",b["rejeicoes"][0]["motivo"])

    def test_linha_sem_duv_nao_publica(self):
        cat,esc=self.simulados()
        x=preparar_portos_para_briefing(
            [self.exemplo(duv=None)],self.licencas(),
            gerado_em=AGORA,catalogo=cat,escopo=esc)
        self.assertEqual(x["indicadores"],[])
        self.assertIn("DUV",x["rejeicoes"][0]["motivo"])

    def test_contagem_multiplas_cargas_mesmo_duv(self):
        cat,esc=self.simulados()
        x=preparar_portos_para_briefing(
            [self.exemplo(),self.exemplo(produto="MILHO",lote_id="LOTE-2")],
            self.licencas(),gerado_em=AGORA,catalogo=cat,escopo=esc)
        self.assertEqual(len(x["painel"]),2)
        self.assertEqual({v["produto"] for v in x["painel"]},{"SOJA","MILHO"})
        self.assertEqual(sum(v["escalas_distintas"] for v in x["painel"]),2)

    def test_sem_registros_nao_relata_porto_vazio(self):
        x=montar_briefing_com_portos(
            noticias=[],fontes_noticias={},indicadores=[],
            registros_portuarios=[],licencas_portuarias={},
            gerado_em=AGORA)
        self.assertEqual(x["status_portuario"],"DADOS_INDISPONIVEIS_OU_NAO_HOMOLOGADOS")
        self.assertEqual(x["painel_portuario"],[])


if __name__ == "__main__":
    unittest.main()
