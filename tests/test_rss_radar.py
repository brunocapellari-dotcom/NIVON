import unittest

from nivon.rss_radar import ErroFeed, ler_feed_xml
from nivon.coleta_web import FonteWeb, adquirir_fonte

AGORA="2026-10-20T10:00:00-03:00"
URL="https://news.example.org/rss"
DOMAIN={"news.example.org"}


def rss(pub="Tue, 20 Oct 2026 09:00:00 -0300"):
    return (f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
    <title>Feed Agro</title>
    <item>
      <title>Plantio do milho verão alcança novo patamar</title>
      <link>https://news.example.org/mercado/milho</link>
      <guid>noticia-123</guid>
      <pubDate>{pub}</pubDate>
      <description><![CDATA[Indicadores apontam avanço no plantio do milho.]]></description>
    </item></channel></rss>""").encode()


def atom(published=True):
    pub="<published>2026-10-19T10:00:00-03:00</published>" if published else ""
    return ("""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Nivon Fonte</title>
      <entry><id>urn:uuid:teste123</id>
        <title>Exportação brasileira registra mudança</title>
        <updated>2026-10-20T09:00:00-03:00</updated>"""+pub+"""
        <link rel="alternate" href="https://news.example.org/comex"/>
        <summary>Publicação sobre exportações e dados agrícolas.</summary>
      </entry>
    </feed>""").encode()


class TestRSSRadar(unittest.TestCase):
    def parse(self,data):
        return ler_feed_xml(data,fonte_id="RADAR_OFICIAL",
                            dominios_artigos=DOMAIN,coletado_em=AGORA,url_feed=URL)

    def test_rss_preserva_publicacao_original(self):
        result=self.parse(rss())
        self.assertEqual(result["formato"],"RSS2")
        self.assertEqual(len(result["candidatos"]),1)
        self.assertEqual(result["candidatos"][0]["publicado_em_original"],"2026-10-20T12:00:00+00:00")
        self.assertIn("NAO_CLASSIFICADO",result["candidatos"][0]["estado"])

    def test_atom_com_published_valido(self):
        result=self.parse(atom())
        self.assertEqual(result["formato"],"ATOM")
        self.assertEqual(len(result["candidatos"]),1)
        self.assertEqual(result["candidatos"][0]["guid"],"urn:uuid:teste123")

    def test_atom_updated_nao_e_publicacao(self):
        result=self.parse(atom(published=False))
        self.assertEqual(result["candidatos"],[])
        self.assertIn("original",result["rejeicoes"][0]["motivo"])

    def test_sem_timezone_rejeita(self):
        result=self.parse(rss("Tue, 20 Oct 2026 09:00:00"))
        self.assertEqual(result["candidatos"],[])
        self.assertIn("fuso",result["rejeicoes"][0]["motivo"])

    def test_html_em_link_rejeitado(self):
        out=self.parse(rss().replace(b"https://news.example.org/mercado/milho",
                                     b"http://news.example.org/mercado/milho"))
        self.assertEqual(out["candidatos"],[])

    def test_xml_com_doctype_ou_entidade_bloqueado(self):
        data=b'<!DOCTYPE rss [<!ENTITY x "boom">]><rss></rss>'
        with self.assertRaises(ErroFeed):
            self.parse(data)

    def test_feed_excessivo_bloqueado(self):
        with self.assertRaises(ErroFeed):
            self.parse(b"x"*(2_000_001))

    def test_xml_de_bloqueio_nao_e_rss(self):
        with self.assertRaises(ErroFeed):
            self.parse(b"<html><body>Request Rejected by WAF</body></html>")

    def test_coleta_xml_apenas_licenciada(self):
        f=FonteWeb("RADAR_OFICIAL",URL,"news.example.org","XML",
                   status_direitos="APROVADA",operacoes_permitidas=frozenset({"COLETA"}))
        class Resposta:
            status=200
            headers={"Content-Type":"application/rss+xml"}
            def geturl(self):return URL
            def read(self,n):return rss()
            def __enter__(self):return self
            def __exit__(self,*args):return False
        class Abridor:
            def open(self,request,timeout):return Resposta()
        got=adquirir_fonte(f,abridor=Abridor())
        self.assertEqual(self.parse(got["conteudo"])["formato"],"RSS2")
        self.assertEqual(got["mime"],"application/rss+xml")

    def test_licenca_pendente_nao_chama_http(self):
        f=FonteWeb("RADAR_OFICIAL",URL,"news.example.org","XML")
        class Abridor:
            def open(self,request,timeout):
                raise AssertionError("A fonte não deveria abrir conexão")
        with self.assertRaises(PermissionError):
            adquirir_fonte(f,abridor=Abridor())


if __name__=="__main__":
    unittest.main()
