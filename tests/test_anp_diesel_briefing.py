import unittest

from nivon.anp_diesel_briefing import montar_indicadores_diesel, ErroDieselBriefing
from nivon.briefing_composto import montar_briefing

SHA="a"*64
AGORA="2026-10-20T10:00:00-03:00"
PUB="2026-10-11T15:14:00-03:00"

def sample(week="2026-10-10"):
    return {
      "dataset_id":"ANP_PRECO_REVENDA_DIESEL","fonte":"ANP_RESUMO_LPC_SEMANAL",
      "sha256":SHA,"coletado_em":"2026-10-20T09:00:00-03:00",
      "url_origem":"https://www.gov.br/anp/pt-br/assuntos/precos/arquivos-lpc/2026/ficheiro.xlsx",
      "observacoes":[
        {"uf":"MT","municipio":"SINOP","produto":"DIESEL S10",
         "semana_inicio_oficial":"2026-10-04","semana_fim_oficial":week,
         "preco_medio_revenda_rs_l":6.15,"postos_pesquisados":7},
        {"uf":"MT","municipio":"SORRISO","produto":"DIESEL",
         "semana_inicio_oficial":"2026-10-04","semana_fim_oficial":week,
         "preco_medio_revenda_rs_l":5.89,"postos_pesquisados":5},
      ]}

def ds(on=True):
    return {"id":"ANP_PRECO_REVENDA_DIESEL","enabled":on,
            "collection_authorized":on,"commercial_redistribution_authorized":on}

def lic():
    return {"status":"APROVADA","evidencia_id":"PROVA_FICTICIA_LICENCA_ANP",
            "layout_real_sha256":SHA,
            "operacoes":["LEITURA","COLETA","ARMAZENAMENTO","PUBLICACAO_DERIVADA"]}

def build(**kw):
    args={"gerado_em":AGORA,"publicado_em":PUB,
          "dataset":ds(),"direitos":lic(),"layout_homologado":True}
    args.update(kw)
    dado=args.pop("resultado",sample())
    return montar_indicadores_diesel(dado,**args)

class TestDieselBriefing(unittest.TestCase):
    def test_preco_diesel_por_municipio_e_tipo(self):
        x=build()
        self.assertEqual(len(x["indicadores"]),2)
        self.assertEqual({r["secao"] for r in x["indicadores"]},{"DIESEL"})
        self.assertTrue(any("SINOP" in r["titulo"] and "DIESEL S10" in r["titulo"]
                            for r in x["indicadores"]))
        self.assertTrue(any("SORRISO" in r["titulo"] and "DIESEL (" in r["titulo"]
                            for r in x["indicadores"]))
        self.assertIn("amostral",x["evidencia"]["tipo"].lower())
        msg=montar_briefing(noticias=[],fontes=x["fontes"],data=AGORA,
                           indicadores=x["indicadores"])
        self.assertIn("SINOP",msg["texto"])
        self.assertIn("SORRISO",msg["texto"])
        self.assertNotIn("paridade",msg["texto"].lower())

    def test_sem_permissao_nao_publica(self):
        with self.assertRaises(PermissionError):
            build(dataset=ds(False))
        with self.assertRaises(PermissionError):
            build(layout_homologado=False)

    def test_sem_prova_xlsx_real_rejeita(self):
        d=lic();d["layout_real_sha256"]="b"*64
        with self.assertRaisesRegex(ErroDieselBriefing,"arquivo diverge"):
            build(direitos=d)

    def test_preco_antigo_rejeitado(self):
        with self.assertRaisesRegex(ErroDieselBriefing,"defasada"):
            build(gerado_em="2026-11-12T10:00:00-03:00")

    def test_publicacao_antes_do_fim_da_semana_rejeitada(self):
        with self.assertRaisesRegex(ErroDieselBriefing,"anterior ao fim"):
            build(publicado_em="2026-10-09T15:14:00-03:00")

    def test_horario_noite_brasilia_nao_converte_semana_para_dia_utc(self):
        self.assertEqual(len(build(
            gerado_em="2026-10-24T23:30:00-03:00")["indicadores"]),2)
        with self.assertRaisesRegex(ErroDieselBriefing,"defasada"):
            build(gerado_em="2026-10-25T00:01:00-03:00")
        with self.assertRaisesRegex(ErroDieselBriefing,"anterior ao fim"):
            build(publicado_em="2026-10-09T23:30:00-03:00")

    def test_publicacao_futura_rejeitada(self):
        with self.assertRaisesRegex(ErroDieselBriefing,"posterior"):
            build(publicado_em="2026-10-21T09:00:00-03:00")

    def test_nao_inventa_municipio_sem_amostra(self):
        with self.assertRaisesRegex(ErroDieselBriefing,"sem dados"):
            build(municipios=frozenset({"LUCAS DO RIO VERDE"}))

    def test_preco_postos_invalidos_rejeita(self):
        x=sample();x["observacoes"][0]["postos_pesquisados"]=0
        with self.assertRaisesRegex(ErroDieselBriefing,"amostral"):
            build(resultado=x)

    def test_semana_incoerente_rejeita(self):
        x=sample("2026-10-08")
        with self.assertRaisesRegex(ErroDieselBriefing,"duração"):
            build(resultado=x)

if __name__=="__main__":
    unittest.main()
