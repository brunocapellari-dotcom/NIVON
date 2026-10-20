"""Alertas operacionais NIVON com relógio injetado e bancos efêmeros."""
import hashlib
import unittest

from nivon.observabilidade_local import monitorar_operacao, ErroObservabilidade
from nivon.progresso_store import abrir_progresso, gravar_progresso
from nivon.conab_agrobr import normalizar_progresso
from nivon.portos_store import abrir_historico_portos, gravar_documento_porto
from nivon.portos import Programacao
from nivon.outbox_briefing import abrir_outbox, agendar_briefing
from datetime import datetime, timezone

NOW="2026-10-20T12:00:00+00:00"
ANTIGO="2026-10-05T12:00:00+00:00"
CONAB="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture"
URL="https://www.portodesantos.com.br/atracacoes-programadas/"


class TestObservabilidadeLocal(unittest.TestCase):
    def setUp(self):
        self.conab=abrir_progresso()
        self.portos=abrir_historico_portos()
        self.outbox=abrir_outbox()

    def tearDown(self):
        self.conab.close()
        self.portos.close()
        self.outbox.close()

    def monitorar(self,ports=("SANTOS",)):
        return monitorar_operacao(
            gerado_em=NOW,conab=self.conab,portos=self.portos,
            outbox=self.outbox,portos_esperados=ports)

    def add_conab(self,stamp):
        linhas=normalizar_progresso([{
            "cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
            "uf":"MT","semana_atual":"2026-10-02","pct_semana_atual":.23,
        }],fonte_url=CONAB,coletado_em=datetime.fromisoformat(stamp),
        publicado_em="2026-10-02T11:00:00+00:00")
        gravar_progresso(self.conab,linhas,evidence_id="FIXTURE",
                         direitos_confirmados=True)

    def add_porto(self,stamp):
        item=Programacao(porto="SANTOS",navio="NAVIO MOCK",duv="D123",
                          imo="1234567",produto="SOJA",fonte=URL,
                          toneladas_programadas=None,coletado_em=stamp,
                          status="PROGRAMADO")
        gravar_documento_porto(self.portos,{
            "status":"EXTRAIDO_AGUARDA_HOMOLOGACAO","porto":"SANTOS",
            "fonte":URL,"documento_sha256":hashlib.sha256(b"documento").hexdigest(),
            "capturado_em":stamp,"registros":[item],
        },evidence_id="FIXTURE",direitos_confirmados=True)

    def add_outbox(self,stamp):
        text="boletim ficcional"
        return agendar_briefing(self.outbox,dia_local="2026-10-05",
            destinatario_hmac="0"*64,
            briefing={"texto":text,"sha256":hashlib.sha256(text.encode()).hexdigest(),
                      "status":"PREPARADO_SEM_ENVIO"},
            agora=stamp,auditoria_aprovada=True)

    def test_sem_bancos_nao_significa_sem_incidentes(self):
        v=monitorar_operacao(gerado_em=NOW)
        self.assertEqual(v["cobertura"]["conab"],"NAO_CONFIGURADO")
        self.assertFalse(v["prova_de_ausencia_de_incidente"])
        self.assertEqual(v["execucao"],"SOMENTE_LEITURA")

    def test_historia_sem_coleta_alerta(self):
        v=self.monitorar()
        codes={a["codigo"] for a in v["alertas"]}
        self.assertIn("CONAB_SEM_COLETA",codes)
        self.assertIn("PORTO_SEM_COLETA",codes)

    def test_conab_porto_atrasados_alertam(self):
        self.add_conab(ANTIGO)
        self.add_porto(ANTIGO)
        v=self.monitorar()
        codes={a["codigo"] for a in v["alertas"]}
        self.assertIn("CONAB_ATRASADA",codes)
        self.assertIn("PORTO_ATRASADO",codes)
        self.assertFalse(v["coleta_automatica"])

    def test_dados_recentes_nao_inventam_alertas(self):
        self.add_conab(NOW)
        self.add_porto(NOW)
        v=self.monitorar()
        self.assertEqual(v["alertas"],[])
        self.assertEqual(v["estado"],"SEM_ALERTAS_NA_COBERTURA_LOCAL")
        self.assertFalse(v["prova_de_ausencia_de_incidente"])

    def test_pendente_antigo_na_outbox_alerta_sem_vazar_hmac(self):
        self.add_outbox(ANTIGO)
        v=self.monitorar(ports=())
        alertas=[a for a in v["alertas"] if a["codigo"]=="OUTBOX_NAO_CONCILIADA"]
        self.assertEqual(len(alertas),1)
        self.assertIn("PENDING",alertas[0]["detalhe"])
        self.assertNotIn("0000000000000000",str(v))
        self.assertFalse(v["reenvio_automatico"])

    def test_banco_quebrado_bloqueia_silencio(self):
        self.conab.close()
        v=monitorar_operacao(gerado_em=NOW,conab=self.conab)
        self.assertEqual(v["cobertura"]["conab"],"ERRO_BANCO")
        self.assertIn("CONAB_BANCO_INVALIDO",{a["codigo"] for a in v["alertas"]})

    def test_portos_repetidos_e_relogio_sem_fuso_recusados(self):
        with self.assertRaises(ErroObservabilidade):
            monitorar_operacao(gerado_em=NOW,portos_esperados=("SANTOS","SANTOS"))
        with self.assertRaises(ErroObservabilidade):
            monitorar_operacao(gerado_em="2026-10-20T12:00:00")

    def test_coleta_futura_alerta(self):
        futuro="2026-10-21T12:00:00+00:00"
        self.add_conab(futuro)
        self.add_porto(futuro)
        r=self.monitorar()
        codes={a["codigo"] for a in r["alertas"]}
        self.assertEqual(codes,{"CONAB_COLETA_FUTURA","PORTO_COLETA_FUTURA"})


if __name__=="__main__":
    unittest.main()
