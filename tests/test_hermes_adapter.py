"""Contrato assíncrono NIVON com Hermes; somente leitura e zero side effects."""
import asyncio
import hashlib
import inspect
import unittest
from datetime import datetime, timezone

from nivon.hermes_adapter import NivonProjectAdapter, ErroIntegracaoHermes
from nivon.progresso_store import abrir_progresso, gravar_progresso
from nivon.conab_agrobr import normalizar_progresso
from nivon.portos_store import abrir_historico_portos, gravar_documento_porto
from nivon.portos import Programacao

NOW="2026-10-20T12:00:00+00:00"
CONAB_URL="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture"
PORTO_URL="https://www.portodesantos.com.br/atracacoes-programadas/"
FONTES={
    "CONAB":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
    "LINEUP_SANTOS":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
    "BCB":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
    "CME":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
}
INDICADORES=[
    {"fonte_id":"CME","secao":"BOLSAS","titulo":"Teste bolsa",
     "valor":"430 c/bu (sintetico)","referencia":NOW,"fonte":"CME mock"},
    {"fonte_id":"BCB","secao":"CAMBIO","titulo":"Teste dolar",
     "valor":"R$ 5,00 (sintetico)","referencia":NOW,"fonte":"BCB mock"},
]
PROGRESSO={"cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
           "uf":"MT","semana":"2026-10-16","gerado_em":NOW}


class TestProjectAdapterHermes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.c=abrir_progresso()
        self.p=abrir_historico_portos()
        registro=normalizar_progresso(
            [{"cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
              "uf":"MT","semana_atual":"2026-10-16","pct_semana_atual":0.39}],
            fonte_url=CONAB_URL,
            coletado_em=datetime(2026,10,20,8,tzinfo=timezone.utc),
            publicado_em="2026-10-19T16:00:00+00:00")
        gravar_progresso(self.c,registro,evidence_id="TESTE",
                        direitos_confirmados=True)
        p=Programacao(porto="SANTOS",navio="NAVIO TESTE",duv="D1",
                      imo="1234567",produto="SOJA",toneladas_programadas=1000,
                      fonte=PORTO_URL,coletado_em=NOW,status="PROGRAMADO")
        gravar_documento_porto(self.p,{
            "status":"EXTRAIDO_AGUARDA_HOMOLOGACAO",
            "porto":"SANTOS","fonte":PORTO_URL,"documento_sha256":hashlib.sha256(b"teste").hexdigest(),
            "capturado_em":NOW,"registros":[p],
        },evidence_id="FIXTURE",direitos_confirmados=True)
        self.allowed={"NIVON_READ"}
        self.adapter=NivonProjectAdapter(
            autorizador=lambda scope: scope in self.allowed,
            fontes=FONTES,conab=self.c,portos=self.p)

    def tearDown(self):
        self.c.close()
        self.p.close()

    async def test_contrato_estrutural_hermes(self):
        for name in ("health","status","capabilities","query","execute","search","alerts"):
            self.assertTrue(inspect.iscoroutinefunction(getattr(self.adapter,name)))
        self.assertEqual(self.adapter.key,"NIVON")
        h=await self.adapter.health()
        self.assertFalse(h["production_ready"])
        self.assertEqual(h["bancos"]["conab"],"QUERY_OK")
        self.assertFalse((await self.adapter.status())["external_actions"])

    async def test_leitura_de_progresso_com_evidencia(self):
        resp=await self.adapter.query("safra.progress.read",PROGRESSO)
        self.assertEqual(resp["status"],"INDICADOR_VERIFICADO_TEMPO")
        self.assertIn("39.0%",resp["indicador"]["valor"])
        self.assertEqual(resp["evidencia"]["modelo"],"VARIACAO_CONTABIL_NAO_PREDITIVA")

    async def test_leitura_porto_somente_programado(self):
        resp=await self.adapter.query("portos.lineup.read",
                                      {"porto":"SANTOS","gerado_em":NOW})
        self.assertEqual(resp["status"],"INDICADOR_VERIFICADO_TEMPO")
        self.assertIsNone(resp["evidencia"]["volume_reportado_t"])
        self.assertIn("PROGRAMACAO",resp["evidencia"]["classificacao"])

    async def test_preview_integra_safra_porto_cbot_e_dolar(self):
        payload={"gerado_em":NOW,"culturas":[{k:v for k,v in PROGRESSO.items() if k!="gerado_em"}],
                 "portos":["SANTOS"],"indicadores":INDICADORES}
        resp=await self.adapter.query("briefing.preview",payload)
        self.assertEqual(resp["status"],"PREVIEW_AUDITADO_NAO_PUBLICADO")
        self.assertFalse(resp["envio"])
        self.assertIn("Line-up SANTOS",resp["texto"])
        self.assertIn("SOJA — Semeadura MT",resp["texto"])
        self.assertIn("Teste bolsa",resp["texto"])
        self.assertFalse(resp["modelo_preditivo_homologado"])

    async def test_nao_publica_quando_cbot_ausente(self):
        r=await self.adapter.query("briefing.preview",
                                   {"gerado_em":NOW,"indicadores":INDICADORES[1:]})
        self.assertEqual(r["status"],"BLOQUEADO_INDICADORES_ESSENCIAIS")
        self.assertNotIn("texto",r)

    async def test_nunca_aceita_execucao_escrita(self):
        for action in ("send_whatsapp","deploy","delete","execute","agendar","pagamento"):
            with self.assertRaises(PermissionError):
                await self.adapter.execute(action,{"force":True})

    async def test_sem_identidade_nega_ate_consulta(self):
        self.allowed.clear()
        for coro in (
            self.adapter.health(),
            self.adapter.query("safra.progress.read",PROGRESSO),
            self.adapter.search("portos"),
            self.adapter.alerts(),
        ):
            with self.assertRaises(PermissionError):
                await coro

    async def test_nao_aceita_sql_url_ou_prompt_em_payload(self):
        for payload in (
            {**PROGRESSO,"sql":"SELECT * FROM users"},
            {"gerado_em":NOW,"url":"https://exemplo.com","portos":[]},
            {"gerado_em":NOW,"deploy":True},
        ):
            with self.assertRaises(ErroIntegracaoHermes):
                cap="safra.progress.read" if "cultura" in payload else "briefing.preview"
                await self.adapter.query(cap,payload)

    async def test_direitos_nao_podem_ser_concedidos_pelo_agent(self):
        fontes={"CONAB":{"status_direitos":"PENDENTE","operacoes":[]}}
        adapter=NivonProjectAdapter(
            autorizador=lambda _:True,fontes=fontes,conab=self.c)
        fontes["CONAB"]["status_direitos"]="APROVADA"
        fontes["CONAB"]["operacoes"]=["LEITURA","PUBLICACAO_DERIVADA"]
        r=await adapter.query("safra.progress.read",PROGRESSO)
        self.assertEqual(r["status"],"BLOQUEADO_DIREITOS")

    async def test_bancos_ausentes_nao_viram_informacao(self):
        adapter=NivonProjectAdapter(
            autorizador=lambda _:True,fontes=FONTES)
        self.assertEqual(
            (await adapter.query("safra.progress.read",PROGRESSO))["status"],
            "SEM_HISTORICO")
        self.assertFalse((await adapter.status())["whatsapp_delivery_enabled"])

    async def test_contexto_excessivo_ou_nao_json_bloqueia(self):
        with self.assertRaises(ErroIntegracaoHermes):
            await self.adapter.query("briefing.preview", {
                "gerado_em": NOW,
                "noticias": [{"titulo": "X" * 70_000}],
            })
        with self.assertRaises(ErroIntegracaoHermes):
            await self.adapter.query("briefing.preview", {
                "gerado_em": NOW,
                "noticias": [{"titulo": object()}],
            })

    async def test_busca_apenas_indice_sem_acesso_externo(self):
        r=await self.adapter.search("portos")
        self.assertEqual(r["items"],["portos.lineup.read"])
        self.assertFalse(r["external_research_executed"])
        self.assertEqual((await self.adapter.alerts())["alerts"],[])


if __name__=="__main__":
    unittest.main()
