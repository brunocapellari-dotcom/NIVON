import hashlib
import sqlite3
import unittest

from nivon.curadoria_radar import hash_documento_candidato
from nivon.pipeline_briefing import gerar_edicao_offline, ErroPipelineBriefing
from nivon.rss_radar import ler_feed_xml

AGORA="2026-10-20T09:00:00-03:00"
XML=b'''<?xml version="1.0"?><rss version="2.0"><channel>
 <item><title>Milho verão avança na safra brasileira</title>
 <guid>plantio-milho-20261020</guid>
 <link>https://dados.example.com/noticia/milho</link>
 <pubDate>Tue, 20 Oct 2026 08:00:00 -0300</pubDate>
 <description>Plantio de milho na safra brasileira progrediu na última semana.</description>
 </item></channel></rss>'''


def dados():
    f=ler_feed_xml(XML,fonte_id="RADAR_ORIGEM",
                   dominios_artigos={"dados.example.com"},
                   coletado_em="2026-10-20T08:30:00-03:00",
                   url_feed="https://dados.example.com/rss")
    candidate=f["candidatos"][0]
    return {"fonte_id":"RADAR_ORIGEM",
            "url_feed":"https://dados.example.com/rss",
            "dominios_artigos":["dados.example.com"],
            "coletado_em":"2026-10-20T08:30:00-03:00",
            "politica":{"fonte_id":"RADAR_ORIGEM",
                        "nome":"Portal sintético","status_direitos":"APROVADA",
                        "operacoes":["LEITURA","COLETA","ARMAZENAMENTO",
                                    "RESUMO","PUBLICACAO_DERIVADA"],
                        "licenca_id":"EVIDENCIA_SINTETICA_123"},
            "avaliacoes":{hashlib.sha256(candidate["guid"].encode()).hexdigest():{
                "fonte_id":"RADAR_ORIGEM","status":"APROVADO",
                "evidencia_id":"REVISAO_SINTETICA_20261020",
                "documento_sha256":hash_documento_candidato(candidate),
                "categoria":"SAFRA E PRODUÇÃO",
                "resumo":"A fonte informa avanço do plantio do milho, sem comprovação de volume embarcado.",
            }}}


class TestPipelineBriefing(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")

    def tearDown(self):
        self.db.close()

    def run_pipeline(self,**kwargs):
        data={"gerado_em":AGORA,"feeds":[dados()],
              "snapshots_xml":{"RADAR_ORIGEM":XML},
              "db":self.db}
        data.update(kwargs)
        return gerar_edicao_offline(**data)

    def test_pipeline_rss_ate_mensagem_sem_envio(self):
        result=self.run_pipeline()
        self.assertEqual(result["estado"],"EDICAO_OFFLINE_PREPARADA_SEM_ENVIO")
        self.assertFalse(result["enviado"])
        self.assertEqual(len(result["sha256"]),64)
        self.assertIn("Milho verão",result["texto"])
        self.assertIn("Portal sintético",result["texto"])
        self.assertEqual(result["noticias_recebidas_curadas"],1)
        self.assertEqual(result["status_portuario"],"DADOS_INDISPONIVEIS_OU_NAO_HOMOLOGADOS")
        self.assertEqual(result["fontes_rss"][0]["snapshot_sha256"],hashlib.sha256(XML).hexdigest())

    def test_erro_direitos_reprova_toda_fonte(self):
        f=dados()
        f["politica"]["status_direitos"]="PENDENTE"
        with self.assertRaises(PermissionError):
            self.run_pipeline(feeds=[f])

    def test_noticia_sem_avaliacao_nao_vira_noticia_publicada(self):
        f=dados()
        f["avaliacoes"]={}
        result=self.run_pipeline(feeds=[f])
        self.assertIn("Nenhuma notícia elegível",result["texto"])
        self.assertEqual(result["noticias_recebidas_curadas"],0)
        self.assertTrue(result["rejeicoes"])

    def test_feed_repetido_mesmo_id_nao_pode_ser_incluido(self):
        with self.assertRaises(ErroPipelineBriefing):
            self.run_pipeline(feeds=[dados(),dados()])

    def test_nao_e_permitido_cotacao_e_rss_com_mesmo_id(self):
        with self.assertRaises(ErroPipelineBriefing):
            self.run_pipeline(fontes_indicadores={"RADAR_ORIGEM":{}})

    def test_feed_sem_snapshot_nao_continua(self):
        with self.assertRaises(ErroPipelineBriefing):
            self.run_pipeline(snapshots_xml={})

    def test_sem_rss_gera_alerta_nao_fabrica_noticia(self):
        r=self.run_pipeline(feeds=[],snapshots_xml={})
        self.assertTrue(r["cobertura"]["fontes_rss_sem_aprovacao"])
        self.assertIn("Nenhuma notícia elegível",r["texto"])
        self.assertEqual(r["indicadores_incluidos"],0)

    def test_sem_rights_porto_omite_em_vez_de_criar_zero(self):
        r=self.run_pipeline(registros_portuarios=[{
            "porto_id":"ITAQUI","fonte_id":"PORTO_ITAQUI","produto":"SOJA",
            "situacao":"PROGRAMADO","duv":"D123"
        }])
        self.assertIn("DADOS_INDISPONIVEIS",r["status_portuario"])
        self.assertNotIn("ITAQUI — SOJA",r["texto"])
        self.assertTrue(r["rejeicoes"])


if __name__=="__main__":
    unittest.main()
