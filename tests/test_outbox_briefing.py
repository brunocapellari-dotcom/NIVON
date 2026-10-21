"""Controle diário de entrega: zero WhatsApp externo e sem PII no SQLite."""
import hashlib
import hmac
import unittest

from nivon.outbox_unificada import registrar_decisao_consentimento, mensagem_de_prova

from nivon.outbox_briefing import (
    abrir_outbox, agendar_briefing, reservar_para_entrega,
    registrar_aceite, confirmar_entrega, ErroOutbox,
)

HMAC = "a" * 64
AGORA = "2026-10-19T08:00:00-03:00"


def briefing(texto="teste autorizado"):
    return {"texto":texto,
            "sha256":hashlib.sha256(texto.encode()).hexdigest(),
            "status":"PREPARADO_SEM_ENVIO"}

CHAVE_CONSENTIMENTO_FIXTURE = b"NIVON-CONSENT-FIXTURE-ASSINATURA-NAO-PRODUCAO-000"

def consentir_teste(db, destinatario_hmac, em):
    evidencia = "OPTIN_FIXTURE_SINTETICO_20261021"
    assinatura=hmac.new(
        CHAVE_CONSENTIMENTO_FIXTURE,
        mensagem_de_prova(acao="CONCEDER", destinatario_hmac=destinatario_hmac,
                         evidencia_id=evidencia, em=em),
        hashlib.sha256,
    ).hexdigest()
    return registrar_decisao_consentimento(
        db,acao="CONCEDER",destinatario_hmac=destinatario_hmac,
        evidencia_id=evidencia, em=em,
        assinatura=assinatura, chave_verificacao=CHAVE_CONSENTIMENTO_FIXTURE)


class TestOutbox(unittest.TestCase):
    def setUp(self):
        self.db=abrir_outbox()
        consentir_teste(self.db,HMAC,AGORA)

    def tearDown(self):
        self.db.close()

    def agendar(self, texto="teste autorizado"):
        return agendar_briefing(
            self.db,dia_local="2026-10-19",
            destinatario_hmac=HMAC,briefing=briefing(texto),
            agora=AGORA,auditoria_aprovada=True)

    def test_preparacao_e_idempotencia_por_dia(self):
        a=self.agendar()
        b=self.agendar()
        self.assertTrue(a["nova"])
        self.assertFalse(b["nova"])
        self.assertEqual(a["id"],b["id"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM briefing_outbox").fetchone()[0],1)

    def test_revisao_depois_do_agendamento_nao_envia_duas_vezes(self):
        self.agendar()
        with self.assertRaises(ErroOutbox):
            self.agendar("boletim reescrito")

    def test_reserva_unica_e_recibo_autenticado(self):
        i=self.agendar()["id"]
        token=reservar_para_entrega(self.db,id=i)
        with self.assertRaises(ErroOutbox):
            reservar_para_entrega(self.db,id=i)
        aceite=registrar_aceite(
            self.db,id=i,token=token["token"],provider_message_id="fake-id-1")
        self.assertEqual(aceite["status"],"ACCEPTED_AGUARDA_DELIVERY_ACK")
        with self.assertRaises(PermissionError):
            confirmar_entrega(self.db,provider_message_id="fake-id-1",
                              autenticado=False,quando=AGORA)
        ok=confirmar_entrega(self.db,provider_message_id="fake-id-1",
                             autenticado=True,quando=AGORA)
        self.assertEqual(ok["status"],"ENTREGUE_COM_ACK_AUTENTICADO")
        with self.assertRaises(ErroOutbox):
            confirmar_entrega(self.db,provider_message_id="fake-id-1",
                              autenticado=True,quando=AGORA)

    def test_sem_auditoria_nao_prepara(self):
        with self.assertRaises(PermissionError):
            agendar_briefing(self.db,dia_local="2026-10-19",
               destinatario_hmac=HMAC,briefing=briefing(),agora=AGORA)
        self.assertEqual(self.db.execute("SELECT count(*) FROM briefing_outbox").fetchone()[0],0)

    def test_hash_corrompido_nao_entra(self):
        b=briefing()
        b["sha256"]="1"*64
        with self.assertRaises(ErroOutbox):
            agendar_briefing(self.db,dia_local="2026-10-19",
               destinatario_hmac=HMAC,briefing=b,agora=AGORA,
               auditoria_aprovada=True)

    def test_token_incorreto_nao_finge_aceite(self):
        i=self.agendar()["id"]
        reservar_para_entrega(self.db,id=i)
        with self.assertRaises(ErroOutbox):
            registrar_aceite(self.db,id=i,token="not-token",
                             provider_message_id="abc")


if __name__ == "__main__":
    unittest.main()
