import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.historico_noticias import registrar_observacoes, ErroHistoricoNoticia
from nivon.rss_radar import ler_feed_xml

AGORA="2026-10-20T10:00:00-03:00"
DIREITOS={"RADAR_TESTE":{"status":"APROVADA","evidencia_id":"LICENCA_TESTE_SINTETICA",
                         "operacoes":["LEITURA","ARMAZENAMENTO"]}}


def feed(original="Tue, 20 Oct 2026 08:30:00 -0300",
         guid="primeira-publicacao",
         link="https://news.example.com/soja?utm_source=teste"):
    return (f"""<?xml version="1.0"?><rss version="2.0"><channel>
    <title>Publicações</title><item>
      <title>Exportações de soja registram movimento importante</title>
      <guid>{guid}</guid>
      <pubDate>{original}</pubDate>
      <link>{link.replace('&','&amp;')}</link>
      <description>Texto resumido de mercado de soja no Brasil.</description>
    </item></channel></rss>""").encode()


class TestHistoricoNoticia(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.path=Path(self.tmp.name)/"noticias.sqlite"
        self.db=sqlite3.connect(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def candidatos(self,xml):
        return ler_feed_xml(xml,fonte_id="RADAR_TESTE",
                            dominios_artigos={"news.example.com"},
                            url_feed="https://news.example.com/rss",
                            coletado_em=AGORA)["candidatos"]

    def test_primeiro_registro_sem_texto_integral(self):
        c=self.candidatos(feed())
        a=registrar_observacoes(self.db,c,autorizacao_armazenar=DIREITOS)
        self.assertEqual(a["observacoes"],1)
        self.assertEqual(a["republicacoes_ou_revisoes"],0)
        self.assertEqual(a["resultados"][0]["tipo"],"PRIMEIRA_OBSERVACAO_NAO_PUBLICAVEL")
        payload=self.path.read_bytes()
        self.assertNotIn(b"Exportacoes de soja",payload)
        self.assertNotIn(b"news.example.com/soja",payload)

    def test_mesma_noticia_nao_rejuvenesce(self):
        c=self.candidatos(feed(original="Mon, 19 Oct 2026 09:00:00 -0300"))
        registrar_observacoes(self.db,c,autorizacao_armazenar=DIREITOS)
        rec=self.candidatos(feed(original="Tue, 20 Oct 2026 08:30:00 -0300"))
        r=registrar_observacoes(self.db,rec,autorizacao_armazenar=DIREITOS)
        self.assertEqual(r["republicacoes_ou_revisoes"],1)
        self.assertEqual(r["resultados"][0]["primeiro_publicado_em"],"2026-10-19T12:00:00+00:00")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_noticia_memoria").fetchone()[0],1)

    def test_guid_diferente_mesma_url_conta_uma(self):
        a=self.candidatos(feed(guid="a",link="https://news.example.com/a?utm_source=x"))
        b=self.candidatos(feed(guid="b",link="https://news.example.com/a?utm_source=y"))
        registrar_observacoes(self.db,a,autorizacao_armazenar=DIREITOS)
        r=registrar_observacoes(self.db,b,autorizacao_armazenar=DIREITOS)
        self.assertEqual(r["republicacoes_ou_revisoes"],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_noticia_memoria").fetchone()[0],1)

    def test_sem_direito_nao_cria_registros(self):
        with self.assertRaises(PermissionError):
            registrar_observacoes(self.db,self.candidatos(feed()),autorizacao_armazenar={})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_noticia_memoria").fetchone()[0],0)

    def test_proveniencia_com_timestamp_futuro_rejeitada(self):
        c=self.candidatos(feed())
        c[0]["publicado_em_original"]="2030-10-20T10:00:00Z"
        with self.assertRaises(ErroHistoricoNoticia):
            registrar_observacoes(self.db,c,autorizacao_armazenar=DIREITOS)

    def test_rollback_lote_contendo_registro_invalido(self):
        good=self.candidatos(feed())
        bad=dict(good[0])
        bad["guid"]=""
        with self.assertRaises(ErroHistoricoNoticia):
            registrar_observacoes(self.db,good+[bad],autorizacao_armazenar=DIREITOS)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_noticia_memoria").fetchone()[0],0)

    def test_menor_data_posteriormente_observada_permanece(self):
        later=self.candidatos(feed())
        registrar_observacoes(self.db,later,autorizacao_armazenar=DIREITOS)
        earlier=self.candidatos(feed(original="Mon, 19 Oct 2026 07:00:00 -0300"))
        result=registrar_observacoes(self.db,earlier,autorizacao_armazenar=DIREITOS)
        self.assertEqual(result["resultados"][0]["primeiro_publicado_em"],"2026-10-19T10:00:00+00:00")


if __name__=="__main__":
    unittest.main()
