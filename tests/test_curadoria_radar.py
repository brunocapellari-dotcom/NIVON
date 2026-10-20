import hashlib
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.curadoria_radar import (
    ErroCuradoria, hash_documento_candidato, preparar_noticias_feed,
)
from nivon.rss_radar import ler_feed_xml
from nivon.briefing_composto import montar_briefing

AGORA="2026-10-20T09:00:00-03:00"
POLITICA={"fonte_id":"RADAR_TECNICO","nome":"Fonte Técnica",
          "status_direitos":"APROVADA",
          "operacoes":["LEITURA","ARMAZENAMENTO","COLETA",
                       "RESUMO","PUBLICACAO_DERIVADA"],
          "licenca_id":"LICENCA_TESTE_2026"}


def xml(dt="Tue, 20 Oct 2026 08:00:00 -0300"):
    return (f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>RSS</title><item>
      <title>Plantio do milho verão avança no Brasil</title>
      <link>https://fonte.example.org/artigo/milho</link>
      <guid>guid-milho-01</guid>
      <pubDate>{dt}</pubDate>
      <description>O relatório informa evolução do plantio e umidade do solo.</description>
    </item></channel></rss>""").encode()


class TestCuradoriaRadar(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.db=sqlite3.connect(Path(self.tmp.name)/"radar.sqlite")

    def tearDown(self):
        self.db.close();self.tmp.cleanup()

    def candidatos(self, dt="Tue, 20 Oct 2026 08:00:00 -0300"):
        return ler_feed_xml(xml(dt),fonte_id="RADAR_TECNICO",
                            dominios_artigos={"fonte.example.org"},
                            coletado_em="2026-10-20T08:30:00-03:00",
                            url_feed="https://fonte.example.org/rss")

    def aprovacao(self, candidate, **changes):
        good={"fonte_id":"RADAR_TECNICO","status":"APROVADO",
              "evidencia_id":"EDITORIAL_20261020_MILHO",
              "documento_sha256":hash_documento_candidato(candidate),
              "categoria":"SAFRA E PRODUÇÃO",
              "resumo":"A fonte relata avanço do plantio de milho na janela verificada."}
        good.update(changes)
        return {hashlib.sha256(candidate["guid"].encode()).hexdigest():good}

    def processar(self,feed,avaliacoes,politica=None):
        return preparar_noticias_feed(
            self.db,feed,politica_fonte=politica if politica is not None else POLITICA,
            avaliacoes=avaliacoes,gerado_em=AGORA)

    def test_rss_curado_aparece_no_briefing_sem_envio(self):
        feed=self.candidatos()
        self.assertEqual(len(feed["candidatos"]),1)
        curado=self.processar(feed,self.aprovacao(feed["candidatos"][0]))
        self.assertEqual(len(curado["noticias"]),1)
        b=montar_briefing(noticias=curado["noticias"],
                         fontes=curado["fontes_briefing"],
                         data=AGORA,indicadores=[])
        self.assertIn("Plantio do milho",b["texto"])
        self.assertIn("A fonte relata avanço",b["texto"])
        self.assertEqual(b["status"],"PREPARADO_SEM_ENVIO")

    def test_sem_resumo_editorial_nada_e_publicado(self):
        feed=self.candidatos()
        r=self.processar(feed,{})
        self.assertEqual(r["noticias"],[])
        self.assertIn("nenhuma curadoria",r["rejeicoes"][0]["motivo"])

    def test_sem_licenca_falha_com_tabela_vazia(self):
        feed=self.candidatos()
        p=dict(POLITICA,status_direitos="PENDENTE")
        with self.assertRaises(PermissionError):
            self.processar(feed,self.aprovacao(feed["candidatos"][0]),p)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='nivon_noticia_memoria'"
        ).fetchone()[0],0)

    def test_edicao_aprovada_de_outro_documento_rejeitada(self):
        feed=self.candidatos()
        r=self.processar(feed,self.aprovacao(feed["candidatos"][0],
                           documento_sha256="0"*64))
        self.assertEqual(r["noticias"],[])
        self.assertIn("mudaram",r["rejeicoes"][0]["motivo"])

    def test_publicacao_no_dia_anterior_nao_e_renovada(self):
        early=self.candidatos("Mon, 19 Oct 2026 07:50:00 -0300")
        r=self.processar(early,self.aprovacao(early["candidatos"][0]))
        self.assertEqual(r["noticias"],[])
        fresh=self.candidatos()
        r=self.processar(fresh,self.aprovacao(fresh["candidatos"][0]))
        self.assertEqual(r["noticias"],[])
        self.assertIn("fora da janela",r["rejeicoes"][0]["motivo"])
        self.assertEqual(r["historico"]["republicacoes"],1)

    def test_publicacao_tem_que_ser_anterior_coleta(self):
        feed=self.candidatos("Tue, 20 Oct 2026 08:45:00 -0300")
        with self.assertRaises(Exception):
            self.processar(feed,self.aprovacao(feed["candidatos"][0]))

    def test_resumo_nao_e_texto_bruto_feed(self):
        feed=self.candidatos()
        r=self.processar(feed,self.aprovacao(feed["candidatos"][0]))
        self.assertNotEqual(r["noticias"][0]["resumo"],feed["candidatos"][0]["resumo_bruto"])

    def test_repeticao_mesmo_feed_no_mesmo_dia_nao_duplica_banco(self):
        feed=self.candidatos()
        approval=self.aprovacao(feed["candidatos"][0])
        self.processar(feed,approval)
        r=self.processar(feed,approval)
        self.assertEqual(r["historico"]["republicacoes"],1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_noticia_memoria"
        ).fetchone()[0],1)


if __name__=="__main__":
    unittest.main()
