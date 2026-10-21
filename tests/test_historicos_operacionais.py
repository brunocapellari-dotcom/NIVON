"""E2E offline: versões semanais CONAB, idempotência e line-up com dois snapshots."""
import asyncio
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from types import SimpleNamespace
import unittest

from nivon.conab_agrobr import normalizar_progresso
from nivon.progresso_store import (
    abrir_progresso, gravar_progresso, consultar_progresso_asof,
    atualizar_progresso, ErroHistoricoProgresso,
)
from nivon.coleta_web import FonteWeb
from nivon.portos_automaticos import ContratoPorto, processar_documento_porto
from nivon.portos_store import (
    abrir_historico_portos, gravar_documento_porto,
    historico_porto, ErroHistoricoPortuario,
)

URL = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra"
WEEK = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/teste-uma-semana"
HORA1 = datetime(2026,10,19,15,tzinfo=timezone.utc)
HORA2 = HORA1 + timedelta(days=1)
PUBLICADO = "2026-10-19T12:00:00+00:00"
BASE = {
 "cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
 "uf":"MT","semana_atual":"2026-10-16",
 "pct_semana_atual":0.35,
 "pct_ano_anterior":0.31,
 "pct_semana_anterior":0.22,
 "pct_media_5_anos":0.33,
}


class TestProgressoTemporal(unittest.TestCase):
    def setUp(self):
        self.db=abrir_progresso()

    def tearDown(self):
        self.db.close()

    def normalizar(self, capturado=HORA1, valor=.35, publicado=PUBLICADO):
        return normalizar_progresso(
            [{**BASE,"pct_semana_atual":valor}],
            fonte_url=WEEK,coletado_em=capturado,publicado_em=publicado)

    def salvar(self, registros):
        return gravar_progresso(self.db,registros,evidence_id="CONAB_TERRITORIO_TESTE",
                                direitos_confirmados=True)

    def test_versao_idempotente_e_captura_em_dias_distintos(self):
        a=self.salvar(self.normalizar())
        b=self.salvar(self.normalizar())
        c=self.salvar(self.normalizar(HORA2))
        self.assertTrue(a["nova_edicao"])
        self.assertFalse(b["nova_edicao"])
        self.assertFalse(b["nova_coleta"])
        self.assertFalse(c["nova_edicao"])
        self.assertTrue(c["nova_coleta"])
        self.assertEqual(self.db.execute("select count(*) from progresso_edicoes").fetchone()[0],1)
        self.assertEqual(self.db.execute("select count(*) from progresso_coletas").fetchone()[0],2)

    def test_revisao_preserva_vintage_anterior(self):
        old=self.salvar(self.normalizar())
        new=self.salvar(self.normalizar(HORA2,.40))
        self.assertNotEqual(old["sha256"],new["sha256"])
        self.assertTrue(new["nova_edicao"])
        self.assertEqual(self.db.execute("select count(*) from progresso_edicoes").fetchone()[0],2)
        before=consultar_progresso_asof(
           self.db,cultura="Soja",safra="2026/27",operacao="Semeadura",
           uf="MT",semana="2026-10-16",
           corte_coleta=HORA1.isoformat(),corte_publicacao=PUBLICADO)
        self.assertEqual(before["observacao"]["pct_semana_atual"],0.35)
        after=consultar_progresso_asof(
           self.db,cultura="Soja",safra="2026/27",operacao="Semeadura",
           uf="MT",semana="2026-10-16",
           corte_coleta=HORA2.isoformat(),corte_publicacao=PUBLICADO)
        self.assertEqual(after["observacao"]["pct_semana_atual"],0.40)

    def test_publicacao_desconhecida_nao_vaza_no_backtest(self):
        self.salvar(self.normalizar(publicado=None))
        resultado=consultar_progresso_asof(
           self.db,cultura="Soja",safra="2026/27",operacao="Semeadura",
           uf="MT",semana="2026-10-16",
           corte_coleta=HORA2.isoformat(),corte_publicacao=PUBLICADO)
        self.assertIsNone(resultado)

    def test_bloqueia_direitos_faltantes(self):
        with self.assertRaises(PermissionError):
            gravar_progresso(self.db,self.normalizar(),
                             evidence_id="T",direitos_confirmados=False)
        self.assertEqual(self.db.execute("select count(*) from progresso_edicoes").fetchone()[0],0)

    def test_mesma_semana_duplicada_falha_sem_escrita(self):
        with self.assertRaises(ErroHistoricoProgresso):
            self.salvar(self.normalizar()*2)
        self.assertEqual(self.db.execute("select count(*) from progresso_edicoes").fetchone()[0],0)

    def test_executor_semanal_reusa_semana_sem_duplicar(self):
        class FakeAgrobr:
            async def semanas_disponiveis(self,**kw):
                return [{"url":WEEK,"descricao":"teste"},{"url":WEEK,"descricao":"duplicada"}]
            async def progresso_safra(self,**kw):
                return [BASE], SimpleNamespace(source_url=WEEK)
        a=asyncio.run(atualizar_progresso(
            db=self.db,api=FakeAgrobr(),direitos_confirmados=True,
            evidence_id="PROVA_CONAB",max_semanas=2))
        self.assertEqual(a["semanas_processadas"],1)
        self.assertEqual(a["edicoes_novas"],1)



class TestBackfillPaginado(unittest.TestCase):
    def test_cursor_retroativo_persistente(self):
        db=abrir_progresso()
        url1=WEEK
        url2=WEEK+"-anterior"
        class MockAgrobr:
            async def semanas_disponiveis(self,**kwargs):
                return [{"url":url1,"descricao":"nova"},{"url":url2,"descricao":"antiga"}]
            async def progresso_safra(self,**kwargs):
                url=kwargs["semana_url"]
                registro={**BASE,"semana_atual":"2026-10-09" if url==url2 else "2026-10-16"}
                return [registro],SimpleNamespace(source_url=url)
        params=dict(db=db,api=MockAgrobr(),max_semanas=1,
                    direitos_confirmados=True,evidence_id="BACKFILL_TESTE")
        a=asyncio.run(atualizar_progresso(**params))
        b=asyncio.run(atualizar_progresso(**params,depois_de_url=a["proximo_cursor"]))
        self.assertEqual(a["restam_na_listagem"],1)
        self.assertEqual(b["restam_na_listagem"],0)
        self.assertEqual(b["edicoes_novas"],1)
        self.assertEqual(db.execute("select count(*) from progresso_edicoes").fetchone()[0],2)
        db.close()

    def test_cursor_nao_encontrado_bloqueia(self):
        db=abrir_progresso()
        class MockAgrobr:
            async def semanas_disponiveis(self,**kwargs):
                return [{"url":WEEK,"descricao":"nova"}]
        with self.assertRaises(ErroHistoricoProgresso):
            asyncio.run(atualizar_progresso(
                db=db,api=MockAgrobr(),depois_de_url=WEEK+"-desconhecida",
                direitos_confirmados=True,evidence_id="TESTE"))
        db.close()


class TestPortosTemporal(unittest.TestCase):
    def setUp(self):
        self.db=abrir_historico_portos()
        self.url="https://www.portodesantos.com.br/atracacoes-programadas/"
        self.fonte=FonteWeb(
            "LINEUP_SANTOS",self.url,"www.portodesantos.com.br","HTML",
            status_direitos="APROVADA",
            operacoes_permitidas=frozenset({"COLETA"}))
        self.contrato=ContratoPorto("SANTOS",self.fonte,"HTML_SANTOS_SCHEDULE")
        self.html=(
            "<table><tr><th>Navio</th><th>IMO</th><th>ETA</th><th>DUV</th>"
            "<th>Evento</th><th>Local</th></tr>"
            "<tr><td>NAVIO TESTE</td><td>1234567</td><td>21/10/2026</td>"
            "<td>D-1</td><td>ATRACACAO</td><td>Berço A</td></tr></table>"
        ).encode()

    def tearDown(self):
        self.db.close()

    def extrair(self,tempo=HORA1, payload=None):
        payload=payload or self.html
        return processar_documento_porto(self.contrato,{
            "conteudo":payload,
            "sha256":sha256(payload).hexdigest(),
            "url":self.url,
            "capturado_em":tempo.isoformat()
        })

    def gravar(self,item):
        return gravar_documento_porto(
            self.db,item,evidence_id="PORTO_PUBLICO_FIXTURE",
            direitos_confirmados=True)

    def test_capture_duplo_mesma_fonte_sem_nova_versao(self):
        um=self.gravar(self.extrair())
        dois=self.gravar(self.extrair(HORA2))
        self.assertTrue(um["nova_versao"])
        self.assertFalse(dois["nova_versao"])
        self.assertTrue(dois["nova_captura"])
        self.assertEqual(self.db.execute("select count(*) from porto_docs").fetchone()[0],1)
        self.assertEqual(self.db.execute("select count(*) from porto_capturas").fetchone()[0],2)

    def test_eta_e_terminal_e_programado_preservados(self):
        self.gravar(self.extrair())
        linhas=historico_porto(self.db,porto="SANTOS",corte_coleta=HORA1.isoformat())
        self.assertEqual(len(linhas),1)
        self.assertEqual(linhas[0]["terminal"],"Berço A")
        self.assertEqual(linhas[0]["eta_programado"],"21/10/2026")
        self.assertEqual(linhas[0]["status"],"PROGRAMADO")
        self.assertEqual(linhas[0]["duv"],"D-1")

    def test_tempo_anterior_nao_exibe_escala_futura(self):
        self.gravar(self.extrair())
        lista=historico_porto(self.db,porto="SANTOS",
                              corte_coleta="2026-10-18T23:59:00+00:00")
        self.assertEqual(lista,[])

    def test_direitos_faltantes_bloqueiam(self):
        with self.assertRaises(PermissionError):
            gravar_documento_porto(self.db,self.extrair(),
                                  evidence_id="x",direitos_confirmados=False)

    def test_mudanca_documento_cria_novo_snapshot(self):
        a=self.gravar(self.extrair())
        b=self.gravar(self.extrair(HORA2,self.html.replace(b"NAVIO TESTE",b"NAVIO NOVO")))
        self.assertTrue(b["nova_versao"])
        atual=historico_porto(self.db,porto="SANTOS",corte_coleta=HORA2.isoformat())
        self.assertEqual(atual[0]["navio"],"NAVIO NOVO")


if __name__=="__main__":
    unittest.main()
