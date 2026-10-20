"""Rotina diária NIVON: CBOT/câmbio obrigatórios, dry-run e outbox sem envio."""
import unittest

from nivon.rotina_diaria import preparar_rotina, ErroRotina
from nivon.outbox_briefing import abrir_outbox

DATA="2026-10-19T12:00:00+00:00"
REF="2026-10-19T11:00:00+00:00"
FONTES={
    "CME":{"status_direitos":"APROVADA",
           "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
    "BCB":{"status_direitos":"APROVADA",
           "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
}
# Apenas fixtures; nenhuma licença de bolsa real é inferida deste teste.
PACOTE={
    "noticias":[],"fretes":[],"fontes":FONTES,
    "indicadores":[
        {"fonte_id":"CME","secao":"BOLSAS","titulo":"Milho CBOT TESTE",
         "valor":"450 centavos/bushel","fonte":"CME FIXTURE","referencia":REF},
        {"fonte_id":"BCB","secao":"CAMBIO","titulo":"Dolar PTAX TESTE",
         "valor":"R$ 5,00","fonte":"BCB FIXTURE","referencia":REF},
    ]
}


class TestRotinaDiaria(unittest.TestCase):
    def setUp(self):
        self.db=abrir_outbox()

    def tearDown(self):
        self.db.close()

    def test_falta_cbot_nao_gera_briefing_publicavel(self):
        pacote={**PACOTE,"indicadores":PACOTE["indicadores"][1:]}
        result=preparar_rotina(pacote=pacote,gerado_em=DATA,auditor=lambda x: True)
        self.assertEqual(result["status"],"BLOQUEADO_INDICADORES_ESSENCIAIS")
        self.assertEqual(result["faltam"],["BOLSAS"])

    def test_auditoria_ausente_bloqueia(self):
        result=preparar_rotina(pacote=PACOTE,gerado_em=DATA)
        self.assertEqual(result["status"],"AGUARDA_AUDITOR")
        self.assertFalse(result["agendado"])

    def test_dry_run_mostra_conteudo_sem_enviar(self):
        result=preparar_rotina(pacote=PACOTE,gerado_em=DATA,
                              auditor=lambda x: True)
        self.assertEqual(result["status"],"VALIDADO_DRY_RUN")
        self.assertIn("Milho CBOT TESTE",result["texto"])
        self.assertFalse(result["previsao_envio"])

    def test_recusa_auditoria(self):
        result=preparar_rotina(pacote=PACOTE,gerado_em=DATA,
                              auditor=lambda x: False,agendar=True)
        self.assertEqual(result["status"],"REPROVADO_AUDITORIA")
        self.assertEqual(self.db.execute(
            "select count(*) from briefing_outbox").fetchone()[0],0)

    def test_idempotencia_dia_e_destinatario(self):
        config=dict(pacote=PACOTE,gerado_em=DATA,auditor=lambda x: True,
                    db=self.db,destinatario_hmac="e"*64,agendar=True)
        a=preparar_rotina(**config)
        b=preparar_rotina(**config)
        self.assertEqual(a["status"],"AGENDADO_NA_OUTBOX_SEM_ENVIO")
        self.assertEqual(a["dia_local"],"2026-10-19")
        self.assertTrue(a["outbox"]["nova"])
        self.assertFalse(b["outbox"]["nova"])
        self.assertEqual(self.db.execute(
            "select count(*) from briefing_outbox").fetchone()[0],1)

    def test_destinatario_hmac_e_obrigatorio_para_agendar(self):
        with self.assertRaises(ErroRotina):
            preparar_rotina(pacote=PACOTE,gerado_em=DATA,auditor=lambda x: True,
                            db=self.db,agendar=True)


if __name__=="__main__":
    unittest.main()
