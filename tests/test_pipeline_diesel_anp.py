import unittest
import sqlite3

from nivon.pipeline_briefing import gerar_edicao_offline, ErroPipelineBriefing

SHA="a"*64

def amostra():
    return {"resultado":{
        "dataset_id":"ANP_PRECO_REVENDA_DIESEL",
        "fonte":"ANP_RESUMO_LPC_SEMANAL",
        "sha256":SHA,"coletado_em":"2026-10-20T08:00:00-03:00",
        "url_origem":"https://www.gov.br/anp/pt-br/assuntos/precos/arquivos-lpc/2026/amostra.xlsx",
        "observacoes":[{"uf":"MT","municipio":"SINOP","produto":"DIESEL S10",
                        "semana_inicio_oficial":"2026-10-04",
                        "semana_fim_oficial":"2026-10-10",
                        "preco_medio_revenda_rs_l":6.20,"postos_pesquisados":7}]},
       "publicado_em":"2026-10-11T15:00:00-03:00",
       "dataset":{"id":"ANP_PRECO_REVENDA_DIESEL","enabled":True,
                  "collection_authorized":True,
                  "commercial_redistribution_authorized":True},
       "direitos":{"status":"APROVADA","evidencia_id":"TESTE_AUTORIZACAO_SINTETICA",
                  "layout_real_sha256":SHA,
                  "operacoes":["LEITURA","COLETA","ARMAZENAMENTO","PUBLICACAO_DERIVADA"]},
       "layout_homologado":True}


class TestPipelineDieselANP(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
    def tearDown(self):
        self.db.close()

    def edicao(self, **changes):
        p=dict(db=self.db,gerado_em="2026-10-20T09:00:00-03:00",
               feeds=[],snapshots_xml={},diesel_resumos=[amostra()])
        p.update(changes)
        return gerar_edicao_offline(**p)

    def test_diesel_semanal_no_briefing_sem_frete(self):
        x=self.edicao()
        self.assertEqual(x["indicadores_incluidos"],1)
        self.assertEqual(len(x["evidencias_diesel"]),1)
        self.assertIn("SINOP/MT",x["texto"])
        self.assertIn("DIESEL S10",x["texto"])
        self.assertIn("6.200",x["texto"])
        self.assertFalse(x["enviado"])

    def test_evidencia_anp_mantem_amostra_semana_raw_e_reconciliacao(self):
        x=self.edicao()
        self.assertEqual(len(x["evidencias_editoriais"]["cotacoes"]),1)
        p=x["evidencias_editoriais"]["cotacoes"][0]
        self.assertEqual(p["fonte_id"],"ANP")
        self.assertEqual(p["grupo"],"ENERGIA")
        self.assertEqual(p["valor"],"6.2")
        self.assertEqual(p["unidade"],"R$/L")
        self.assertEqual(p["natureza"],"INDICATIVO")
        self.assertEqual(p["competencia"],"2026-10-10")
        self.assertEqual(p["semana_inicio"],"2026-10-04")
        self.assertEqual(p["semana_fim"],"2026-10-10")
        self.assertEqual(p["postos_pesquisados"],7)
        self.assertEqual(p["classe_estatistica"],"MEDIA_AMOSTRAL_MUNICIPAL_REVENDA")
        self.assertEqual(p["sha256_origem"],SHA)
        self.assertEqual(p["evidencia_direitos_id"],"TESTE_AUTORIZACAO_SINTETICA")
        self.assertIn("R$/L",x["texto"])
        self.assertFalse(any(err.startswith("COTACAO_")
                             for err in x["preflight_editorial"]["bloqueios"]))
        self.assertFalse(x["preflight_editorial"]["apto_revisao"])
        self.assertEqual(x["preflight_editorial"]["modo"],"OFFLINE_SEM_ENVIO")

    def test_sem_direito_externo_nao_gera_cotacao(self):
        a=amostra();a["dataset"]["enabled"]=False
        with self.assertRaises(PermissionError):
            self.edicao(diesel_resumos=[a])

    def test_duas_vintages_mesmo_relatorio_nao_passa(self):
        with self.assertRaises(ErroPipelineBriefing):
            self.edicao(diesel_resumos=[amostra(),amostra()])

    def test_resumo_anp_sem_homologacao_real_nao_gera(self):
        a=amostra();a["layout_homologado"]=False
        with self.assertRaises(PermissionError):
            self.edicao(diesel_resumos=[a])

    def test_sem_diesel_continua_padroes(self):
        x=self.edicao(diesel_resumos=[])
        self.assertEqual(x["evidencias_diesel"],[])
        self.assertEqual(x["indicadores_incluidos"],0)

if __name__=="__main__":
    unittest.main()
