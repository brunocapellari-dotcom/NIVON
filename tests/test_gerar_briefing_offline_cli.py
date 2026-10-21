import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.curadoria_radar import hash_documento_candidato
from nivon.rss_radar import ler_feed_xml
from scripts.gerar_briefing_offline import executar, _sob_raiz


XML=('''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>Safra brasileira de soja recebe novas estimativas</title>
<guid>n-2026-soja</guid><link>https://portal.example.org/safra/soja</link>
<pubDate>Tue, 20 Oct 2026 08:00:00 -0300</pubDate>
<description>Boletim registra alterações nas perspectivas de produção agrícola.</description>
</item></channel></rss>''').encode("utf-8")


class TestCLIBriefingOffline(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.snap=self.base/"noticia.xml"
        self.snap.write_bytes(XML)
        self.manifesto=self.base/"edicao.json"
        self.db=self.base/"radar.sqlite"
        self.report=self.base/"briefing.txt"
        self.audit=self.base/"auditoria.json"
        item=ler_feed_xml(XML,fonte_id="PORTAL_AGRO",
                          dominios_artigos={"portal.example.org"},
                          url_feed="https://portal.example.org/rss",
                          coletado_em="2026-10-20T08:30:00-03:00")["candidatos"][0]
        self.dados={"gerado_em":"2026-10-20T09:00:00-03:00",
                    "feeds":[{
                        "fonte_id":"PORTAL_AGRO",
                        "arquivo_xml":"noticia.xml",
                        "url_feed":"https://portal.example.org/rss",
                        "dominios_artigos":["portal.example.org"],
                        "coletado_em":"2026-10-20T08:30:00-03:00",
                        "politica":{"fonte_id":"PORTAL_AGRO","nome":"Portal Agro Sintético",
                                    "status_direitos":"APROVADA",
                                    "operacoes":["LEITURA","COLETA","ARMAZENAMENTO",
                                                "RESUMO","PUBLICACAO_DERIVADA"],
                                    "licenca_id":"LICENCA_FICTICIA_TESTES"},
                        "avaliacoes":{hashlib.sha256(item["guid"].encode()).hexdigest():{
                            "fonte_id":"PORTAL_AGRO","status":"APROVADO",
                            "evidencia_id":"AUDITORIA_FICTICIA_TESTES",
                            "documento_sha256":hash_documento_candidato(item),
                            "categoria":"SAFRA E PRODUÇÃO",
                            "resumo":"O boletim informa revisão das projeções para a produção de soja no país.",
                        }},
                    }]}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        self.manifesto.write_text(json.dumps(self.dados,ensure_ascii=False),encoding="utf-8")

    def do(self):
        return executar(manifesto=self.manifesto,banco=self.db,
                       saida=self.report,auditoria=self.audit)

    def test_gerar_texto_auditoria_sem_envio(self):
        self.write()
        r=self.do()
        self.assertFalse(r["enviado"])
        texto=self.report.read_text(encoding="utf-8")
        self.assertIn("Safra brasileira de soja",texto)
        self.assertIn("Portal Agro Sintético",texto)
        self.assertIn("ÚLTIMAS 24H",texto)
        meta=json.loads(self.audit.read_text(encoding="utf-8"))
        self.assertEqual(meta["noticias_recebidas_curadas"],1)
        self.assertEqual(meta["sha256"],r["sha256"])
        self.assertFalse(meta["enviado"])
        self.assertNotIn("texto",meta)
        self.assertEqual(self.db.stat().st_size>0,True)

    def test_mesma_edicao_se_reexecutada_nao_duplica_evento(self):
        self.write()
        first=self.do()
        second=self.do()
        self.assertEqual(first["sha256"],second["sha256"])
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM nivon_noticia_memoria").fetchone()[0],1)

    def test_caminho_traversal_nao_e_lido(self):
        self.dados["feeds"][0]["arquivo_xml"]="../outro.xml"
        self.write()
        with self.assertRaises(ValueError):
            self.do()

    def test_sem_curadoria_nao_publica_texto_da_fonte(self):
        self.dados["feeds"][0]["avaliacoes"]={}
        self.write()
        self.do()
        text=self.report.read_text(encoding="utf-8")
        self.assertNotIn("Safra brasileira de soja",text)
        self.assertIn("Nenhuma notícia elegível",text)

    def test_feed_em_symlink_nao_e_lido(self):
        try:
            (self.base/"atalho.xml").symlink_to(self.snap)
        except (NotImplementedError,OSError):
            self.skipTest("symlink indisponível")
        self.dados["feeds"][0]["arquivo_xml"]="atalho.xml"
        self.write()
        with self.assertRaises(ValueError):
            self.do()

    def test_nao_escrever_relatorio_sem_direitos(self):
        self.dados["feeds"][0]["politica"]["status_direitos"]="REVIEW"
        self.write()
        with self.assertRaises(PermissionError):
            self.do()
        self.assertFalse(self.report.exists())


if __name__=="__main__":
    unittest.main()
