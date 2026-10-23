"""E2E offline RSS, snapshot HTML, signatures and editor preflight."""
import hashlib
import hmac
import json
import sqlite3
import unittest
from datetime import datetime

from nivon.coleta_web import FonteWeb, adquirir_fonte
from nivon.editorial_preflight import avaliar_previa_editorial
from nivon.proveniencia_rss_editorial import (
    ErroProveniencia, conteudo_assinado, conciliar_rss_com_pagina_e_atestados,
    revisar_edicao_com_custodia_offline,
)
from nivon.registry_emissores import revogar_emissor
from suporte_provas_outbox import provas_sinteticas, provisionar_teste, assinatura_administrativa, RAIZ_SINTETICA
from test_editorial_pipeline_integrado import gerar, feed, XML

URL="https://portal.example.org/noticias/plantio"
HTML=("""<!DOCTYPE html><html><head><title>Plantio</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"NewsArticle",
"url":"https://portal.example.org/noticias/plantio",
"datePublished":"2026-10-20T08:00:00-03:00"}
</script></head><body>Publicação sintética de plantio de soja MT.</body></html>""").encode()


class FakeResposta:
    status=200
    headers={"Content-Type":"text/html; charset=UTF-8"}
    def geturl(self):return URL
    def read(self,n):return HTML[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False


class FakeAbridor:
    def open(self,request,timeout):return FakeResposta()


class TestProvenienciaRSSE2E(unittest.TestCase):
    def setUp(self):
        self.ed=gerar()
        self.candidatos=self.ed["evidencias_editoriais"]
        self.con=sqlite3.connect(":memory:")
        doc={"revisao_editorial_id":"REVISAO_SINTETICA_20261020",
             "direitos_publicacao_id":"DIREITOS_SINTETICOS_20261020",
             "consentimento_id":"CONSENTIMENTO_SINTETICO_20261020",
             "template_aprovado_id":"TEMPLATE_SINTETICO_20261020",
             "orcamento_id":"ORCAMENTO_SINTETICO_20261020",
             "edicao":"2026-10-20","valido_ate":"2026-10-20T23:00:00-03:00",
             "idempotency_key":"a"*64,"sha256_editorial":"b"*64,
             "destinatario_hmac":"c"*64,"payload_sha256":"d"*64}
        _,self.keys=provas_sinteticas(doc)
        provisionar_teste(self.con,self.keys)
        fonte=FonteWeb("PORTAL_EXEMPLO",URL,"portal.example.org","HTML",
             status_direitos="APROVADA",operacoes_permitidas=frozenset({"COLETA"}))
        self.page=adquirir_fonte(fonte,abridor=FakeAbridor(),
            instante=datetime.fromisoformat("2026-10-20T09:00:00-03:00"))
        self.pages={URL:self.page}
        self.events={URL:{"evento_id":"EVENTO_SINTETICO_PLANTIO_MT_20261020",
            "evidencia_evento_id":"DECISAO_SINTETICA_EDITORIAL_20261020"}}
        noticia=self.candidatos["noticias"][0]
        self.att={URL:{}}
        for tipo,papel in (("PUBLICACAO_ORIGINAL","REVISAO_EDITORIAL"),
                           ("DIREITOS_PUBLICACAO","DIREITOS_PUBLICACAO")):
            nome=next(k for k,v in self.keys.items() if v["tipo"]==papel)
            atestado={
                "tipo":tipo,"emissor_id":nome,
                "id_evidencia":"PROVA_SINTETICA_"+tipo+"_20261020",
                "fonte_id":noticia["fonte_id"],"url":noticia["url"],
                "publicado_em":noticia["publicado_em"],
                "coletado_em":noticia["coletado_em"],
                "capturado_em":self.page["capturado_em"],
                "sha256_feed":hashlib.sha256(XML).hexdigest(),
                "sha256_pagina":self.page["sha256"],
                "licenca_id":noticia["evidencia_direitos_id"],
                "operacoes":["COLETA","ARMAZENAMENTO","RESUMO","PUBLICACAO_DERIVADA"],
                "estado":"APROVADA"}
            self.att[URL][tipo]={"documento":atestado,
                                "assinatura":self.assinar(atestado)}
        self.feeds=[feed()]
        self.xml={"PORTAL_EXEMPLO":XML}

    def tearDown(self):
        self.con.close()

    def assinar(self, doc):
        return "sha256="+hmac.new(
            self.keys[doc["emissor_id"]]["chave"],conteudo_assinado(doc),
            hashlib.sha256).hexdigest()

    def conciliar(self):
        return conciliar_rss_com_pagina_e_atestados(
            self.con,candidatos=self.candidatos,feeds=self.feeds,
            snapshots_xml=self.xml,paginas=self.pages,atestados=self.att,
            eventos=self.events,chaves_emissores=self.keys)

    def test_rss_html_duas_assinaturas_para_preflight(self):
        r=self.conciliar()
        self.assertEqual(r["estado"],"ORIGEM_VERIFICADA_OFFLINE_SEM_PUBLICACAO")
        n=r["noticias"][0]
        self.assertTrue(n["publicacao_original_verificada"])
        self.assertEqual(n["sha256_origem"],hashlib.sha256(XML).hexdigest())
        self.assertEqual(n["evidencia_direitos_id"],"LICENCA_TESTE_0001")
        self.assertFalse(r["envio_habilitado"])
        ed=self.ed
        prev=avaliar_previa_editorial(
            edicao={"estado":ed["estado"],"gerado_em":ed["gerado_em"],
                    "texto":ed["texto"],"sha256":ed["sha256"],"enviado":False},
            gerado_em=ed["gerado_em"],noticias=r["noticias"],
            cotacoes=r["cotacoes"],fretes=r["fretes"])
        self.assertFalse(any("data original" in b for b in prev["bloqueios"]))
        self.assertFalse(prev["apto_revisao"]) # outras seções ainda faltam
    def test_sem_licenca_assinada_nao_sobe_status(self):
        del self.att[URL]["DIREITOS_PUBLICACAO"]
        with self.assertRaises(PermissionError):self.conciliar()

    def test_assinatura_falsa_falha(self):
        self.att[URL]["PUBLICACAO_ORIGINAL"]["assinatura"]="sha256="+"0"*64
        with self.assertRaises(PermissionError):self.conciliar()

    def test_publicacao_editada_apos_assinatura_falha(self):
        self.att[URL]["PUBLICACAO_ORIGINAL"]["documento"]["publicado_em"]="2026-10-21T08:00:00-03:00"
        with self.assertRaises(PermissionError):self.conciliar()

    def test_rss_raw_trocado_depois_da_curadoria_falha(self):
        self.xml["PORTAL_EXEMPLO"]=XML.replace(b"avanca",b"evolui")
        with self.assertRaises(PermissionError):self.conciliar()

    def test_html_bytes_alterados_nao_correspondem_sha(self):
        self.pages[URL]=dict(self.page,conteudo=HTML+b"outro")
        with self.assertRaises(ErroProveniencia):self.conciliar()

    def test_data_modificada_nao_substitui_published(self):
        raw=HTML.replace(b"datePublished",b"dateModified")
        self.pages[URL]=dict(self.page,conteudo=raw,sha256=hashlib.sha256(raw).hexdigest())
        with self.assertRaises(ErroProveniencia):self.conciliar()

    def test_data_original_divergente_reprova(self):
        raw=HTML.replace(b"2026-10-20T08:00:00-03:00",b"2026-10-19T08:00:00-03:00")
        self.pages[URL]=dict(self.page,conteudo=raw,sha256=hashlib.sha256(raw).hexdigest())
        with self.assertRaises(PermissionError):self.conciliar()

    def test_pagina_de_url_diferente_reprova(self):
        self.pages[URL]=dict(self.page,url="https://portal.example.org/outro")
        with self.assertRaises(ErroProveniencia):self.conciliar()

    def test_revogacao_de_emissor_invalida_atestado_historico(self):
        nome=self.att[URL]["DIREITOS_PUBLICACAO"]["documento"]["emissor_id"]
        evento={"operacao":"REVOGAR","emissor_id":nome,
                "evidencia_id":"REVOGACAO_SINTETICA_DIREITOS_20261020"}
        revogar_emissor(self.con,evento=evento,
            assinatura=assinatura_administrativa(evento),chave_raiz=RAIZ_SINTETICA)
        with self.assertRaises(PermissionError):self.conciliar()

    def test_licenca_diferente_mesmo_reassinada_falha(self):
        doc=self.att[URL]["DIREITOS_PUBLICACAO"]["documento"]
        doc["licenca_id"]="OUTRA_LICENCA_SINTETICA_20261020"
        self.att[URL]["DIREITOS_PUBLICACAO"]["assinatura"]=self.assinar(doc)
        with self.assertRaises(PermissionError):self.conciliar()

    def test_evento_sem_decisao_editorial_falha(self):
        del self.events[URL]
        with self.assertRaises(ErroProveniencia):self.conciliar()

    def test_ledger_hash_only_registra_idempotente_e_preflight_coletado(self):
        primeiro=revisar_edicao_com_custodia_offline(
            self.con,edicao=self.ed,feeds=self.feeds,snapshots_xml=self.xml,
            paginas=self.pages,atestados=self.att,eventos=self.events,
            chaves_emissores=self.keys,registrar_hashes=True)
        self.assertEqual(primeiro["estado"],"BLOQUEADO_POR_OUTRAS_EVIDENCIAS")
        self.assertFalse(primeiro["envio_habilitado"])
        self.assertEqual(primeiro["evidencias"]["rastreios_gravados"],1)
        segunda=revisar_edicao_com_custodia_offline(
            self.con,edicao=self.ed,feeds=self.feeds,snapshots_xml=self.xml,
            paginas=self.pages,atestados=self.att,eventos=self.events,
            chaves_emissores=self.keys,registrar_hashes=True)
        self.assertEqual(segunda["sha256_edicao"],self.ed["sha256"])
        rows=self.con.execute("SELECT * FROM nivon_proveniencia_editorial").fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][3],hashlib.sha256(XML).hexdigest())
        self.assertEqual(rows[0][4],self.page["sha256"])
        self.assertFalse(any(isinstance(x,str) and URL in x for x in rows))
        self.assertFalse(any(isinstance(x,bytes) and HTML in x for x in rows))

    def test_ledger_rejeita_atestado_substituido_apos_custodia(self):
        self.conciliar_registrando()
        d=self.att[URL]["PUBLICACAO_ORIGINAL"]["documento"]
        d["id_evidencia"]="OUTRA_PROVA_ORIGINAL_SINTETICA_20261020"
        self.att[URL]["PUBLICACAO_ORIGINAL"]["assinatura"]=self.assinar(d)
        with self.assertRaisesRegex(PermissionError,"não pode ser substituída"):
            self.conciliar_registrando()
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM nivon_proveniencia_editorial").fetchone()[0],1)

    def test_sem_direitos_assinados_nao_cria_ledger_nem_parcial(self):
        del self.att[URL]["DIREITOS_PUBLICACAO"]
        with self.assertRaises(PermissionError):self.conciliar_registrando()
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='nivon_proveniencia_editorial'"
        ).fetchone()[0],0)

    def test_ledger_alteracao_de_hash_editorial_falha_fechada(self):
        self.ed["evidencias_editoriais"]["sha256_edicao"]="b"*64
        with self.assertRaisesRegex(ErroProveniencia,"SHA"):
            revisar_edicao_com_custodia_offline(
                self.con,edicao=self.ed,feeds=self.feeds,snapshots_xml=self.xml,
                paginas=self.pages,atestados=self.att,eventos=self.events,
                chaves_emissores=self.keys,registrar_hashes=True)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='nivon_proveniencia_editorial'"
        ).fetchone()[0],0)

    def conciliar_registrando(self):
        return conciliar_rss_com_pagina_e_atestados(
            self.con,candidatos=self.candidatos,feeds=self.feeds,
            snapshots_xml=self.xml,paginas=self.pages,atestados=self.att,
            eventos=self.events,chaves_emissores=self.keys,
            registrar_hashes=True)

    def test_operacao_somente_leitura_nao_persiste_html(self):
        self.assertTrue(self.conciliar()["noticias"])
        nomes={r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("nivon_paginas_html",nomes)


if __name__=="__main__":
    unittest.main()
