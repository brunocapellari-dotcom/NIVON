"""Integração real de contratos SQLite -> indicadores -> briefing sem rede."""
import hashlib
import sqlite3
import unittest
from datetime import datetime,timezone
from nivon.progresso_store import abrir_progresso,gravar_progresso
from nivon.conab_agrobr import normalizar_progresso
from nivon.portos_store import abrir_historico_portos,gravar_documento_porto
from nivon.portos import Programacao
from nivon.indicadores_historicos import (
    indicador_conab,indicador_porto,compor_pacote_historico,ErroPonte,
)
from nivon.rotina_diaria import preparar_rotina

DATA="2026-10-20T12:00:00+00:00"
CONAB_URL="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/exemplo"
PORTO_URL="https://www.portodesantos.com.br/programacao-testes/"
FONTES={
 "CONAB":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
 "LINEUP_SANTOS":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
 "CME":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
 "BCB":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
}
CONTRATO={
 "cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
 "uf":"MT","semana":"2026-10-16"
}


class TestIntegracaoHistoricosBriefing(unittest.TestCase):
    def setUp(self):
        self.c=abrir_progresso()
        self.p=abrir_historico_portos()
        self.add_conab("2026-10-09",.27,"2026-10-09T20:00:00+00:00")
        self.add_conab("2026-10-16",.39,"2026-10-17T20:00:00+00:00")
        prog=Programacao(
            porto="SANTOS",navio="NAVIO TESTE",duv="D-100",
            imo="1111111",produto="SOJA",
            toneladas_programadas=50000.0,
            fonte=PORTO_URL,coletado_em="2026-10-20T08:00:00+00:00",
            status="PROGRAMADO")
        gravar_documento_porto(self.p,{
            "status":"EXTRAIDO_AGUARDA_HOMOLOGACAO","porto":"SANTOS",
            "fonte":PORTO_URL,"documento_sha256":hashlib.sha256("html sintético".encode("utf-8")).hexdigest(),
            "capturado_em":"2026-10-20T08:00:00+00:00","registros":[prog],
        },evidence_id="DOCUMENTO_FIXTURE",direitos_confirmados=True)

    def tearDown(self):
        self.c.close()
        self.p.close()

    def add_conab(self,semana,valor,publicado,uf="MT"):
        r=normalizar_progresso([{
            "cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
            "uf":uf,"semana_atual":semana,"pct_semana_atual":valor,
        }],fonte_url=CONAB_URL,
        coletado_em=datetime(2026,10,20,8,tzinfo=timezone.utc),
        publicado_em=publicado)
        gravar_progresso(self.c,r,evidence_id="CONAB_FIXTURE",direitos_confirmados=True)

    def test_conab_compara_semanas_publicadas_sem_inferir_safra(self):
        r=indicador_conab(
            self.c,gerado_em=DATA,fontes=FONTES,**CONTRATO)
        self.assertEqual(r["status"],"INDICADOR_VERIFICADO_TEMPO")
        self.assertIn("39.0% informado",r["indicador"]["valor"])
        self.assertIn("+12.0 p.p.",r["indicador"]["valor"])
        self.assertEqual(r["evidencia"]["modelo"],"VARIACAO_CONTABIL_NAO_PREDITIVA")
        self.assertEqual(r["indicador"]["referencia"],"2026-10-17T20:00:00+00:00")

    def test_corte_temporal_nao_antecipa_publicacao_nem_coleta(self):
        r=indicador_conab(self.c,fontes=FONTES,gerado_em="2026-10-16T12:00:00+00:00",**CONTRATO)
        self.assertEqual(r["status"],"SEM_OBSERVACAO_ASOF")

    def test_fonte_sem_direitos_nao_vaza_valor(self):
        r=indicador_conab(self.c,fontes={},gerado_em=DATA,**CONTRATO)
        self.assertEqual(r["status"],"BLOQUEADO_DIREITOS")
        self.assertNotIn("indicador",r)

    def test_media_estados_nunca_inferida_como_mt_ou_brasil(self):
        self.add_conab("2026-10-16",.40,"2026-10-18T12:00:00+00:00",uf="MEDIA_ESTADOS")
        r=indicador_conab(self.c,fontes=FONTES,gerado_em=DATA,**CONTRATO)
        self.assertEqual(r["status"],"INDICADOR_VERIFICADO_TEMPO")
        self.assertIn("39.0%",r["indicador"]["valor"])
        media=indicador_conab(self.c,gerado_em=DATA,fontes=FONTES,
                             **{**CONTRATO,"uf":"MEDIA_ESTADOS"})
        self.assertIn("NÃO Brasil",media["indicador"]["valor"])

    def test_porto_escala_programada_nao_vira_embarque(self):
        r=indicador_porto(self.p,porto="SANTOS",gerado_em=DATA,fontes=FONTES)
        self.assertEqual(r["status"],"INDICADOR_VERIFICADO_TEMPO")
        self.assertIn("1 escalas programadas",r["indicador"]["valor"])
        self.assertIsNone(r["evidencia"]["volume_reportado_t"])
        self.assertIn("não prova embarque",r["indicador"]["fonte"])

    def test_porto_antigo_nao_entra(self):
        r=indicador_porto(self.p,porto="SANTOS",
                        gerado_em="2026-10-27T12:00:00+00:00",fontes=FONTES)
        self.assertEqual(r["status"],"DADO_VENCIDO")

    def test_porto_sem_direitos_nao_enche_pacote(self):
        r=indicador_porto(self.p,porto="SANTOS",gerado_em=DATA,fontes={})
        self.assertEqual(r["status"],"BLOQUEADO_DIREITOS")

    def test_end_to_end_com_bolsa_e_cambio_injetados_autorizados(self):
        externos=[
            {"fonte_id":"CME","secao":"BOLSAS",
             "titulo":"Milho CBOT fixture","valor":"440 cents/bu",
             "fonte":"FIXTURE CME, não mercado real","referencia":DATA},
            {"fonte_id":"BCB","secao":"CAMBIO",
             "titulo":"Dólar fixture","valor":"5,00",
             "fonte":"FIXTURE BCB, não mercado real","referencia":DATA},
        ]
        r=compor_pacote_historico(
            db_conab=self.c,db_portos=self.p,gerado_em=DATA,fontes=FONTES,
            culturas=[CONTRATO],portos=["SANTOS"],
            indicadores_externos=externos)
        self.assertEqual(len(r["pacote"]["indicadores"]),4)
        final=preparar_rotina(
            pacote=r["pacote"],gerado_em=DATA,auditor=lambda b: not b["rejeicoes"],
        )
        self.assertEqual(final["status"],"VALIDADO_DRY_RUN")
        self.assertIn("SAFRA",final["texto"])
        self.assertIn("Line-up SANTOS",final["texto"])
        self.assertIn("Milho CBOT fixture",final["texto"])

    def test_bolsa_ausente_impede_envio_mesmo_com_safra_porto(self):
        r=compor_pacote_historico(db_conab=self.c,db_portos=self.p,
                                  fontes=FONTES,gerado_em=DATA,
                                  culturas=[CONTRATO],portos=["SANTOS"])
        final=preparar_rotina(
            pacote=r["pacote"],gerado_em=DATA,auditor=lambda _: True)
        self.assertEqual(final["status"],"BLOQUEADO_INDICADORES_ESSENCIAIS")
        self.assertEqual(final["faltam"],["BOLSAS","CAMBIO"])

    def test_sem_historico_retorna_diagnostico_nao_numero(self):
        r=compor_pacote_historico(db_conab=None,db_portos=None,
                                  fontes=FONTES,gerado_em=DATA,
                                  culturas=[CONTRATO],portos=["SANTOS"])
        self.assertEqual(len(r["pacote"]["indicadores"]),0)
        self.assertEqual([x["status"] for x in r["resultados"]],["SEM_HISTORICO","SEM_HISTORICO"])


if __name__=="__main__":
    unittest.main()
