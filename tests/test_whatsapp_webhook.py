"""Segurança do webhook Meta e transição outbox, exclusivamente offline."""
from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone

from nivon.outbox_unificada import registrar_decisao_consentimento, mensagem_de_prova

from nivon.outbox_briefing import (
    abrir_outbox, agendar_briefing, reservar_para_entrega,
    registrar_aceite,
)
from nivon.whatsapp_webhook import (
    aplicar_webhook_entregas, verificar_assinatura, ErroWebhook,
)

SECRET = "S" * 42
DATE = "2026-10-19T16:00:00+00:00"


def body(status="delivered", mid="wamid.123", timestamp="1792425600"):
    return json.dumps({"object":"whatsapp_business_account","entry":[{
        "changes":[{"field":"messages","value":{"statuses":[{
            "id":mid, "status":status, "timestamp":timestamp,
            "recipient_id":"5511000000000",
        }]}}]
    }]},separators=(",",":")).encode()


def signature(raw):
    return "sha256="+hmac.new(SECRET.encode(),raw,hashlib.sha256).hexdigest()

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


class TestWebhookWhatsapp(unittest.TestCase):
    def setUp(self):
        self.db=abrir_outbox()
        consentir_teste(self.db,"a"*64,DATE)
        texto="brieﬁng sintético sem dados pessoais"
        briefing={
            "status":"PREPARADO_SEM_ENVIO",
            "texto":texto,
            "sha256":hashlib.sha256(texto.encode()).hexdigest(),
        }
        r=agendar_briefing(
            self.db,dia_local="2026-10-19",
            destinatario_hmac="a"*64,
            briefing=briefing,agora=DATE,
            auditoria_aprovada=True)
        res=reservar_para_entrega(self.db,id=r["id"])
        registrar_aceite(self.db,id=r["id"],
                         token=res["token"],provider_message_id="wamid.123")

    def tearDown(self):
        self.db.close()

    def receber(self, raw, sig=None):
        return aplicar_webhook_entregas(
            self.db,raw_body=raw,
            signature=sig or signature(raw),app_secret=SECRET)

    def estado(self):
        return self.db.execute(
            "SELECT status FROM briefing_outbox").fetchone()[0]

    def test_delivered_assinado_confirma(self):
        r=self.receber(body())
        self.assertEqual(r["confirmadas"],1)
        self.assertEqual(self.estado(),"DELIVERED")

    def test_recebido_repetido_nao_muda_duas_vezes(self):
        self.receber(body())
        r=self.receber(body())
        self.assertEqual(r["nao_correspondentes"],1)
        self.assertEqual(self.estado(),"DELIVERED")

    def test_assinatura_falsa_recusada(self):
        with self.assertRaises(PermissionError):
            self.receber(body(), "sha256="+"0"*64)
        self.assertEqual(self.estado(),"ACCEPTED")

    def test_payload_adulterado_sem_nova_assinatura(self):
        raw=body()
        signature_original=signature(raw)
        with self.assertRaises(PermissionError):
            self.receber(raw.replace(b"delivered",b"delivXred"),signature_original)
        self.assertEqual(self.estado(),"ACCEPTED")

    def test_mensagem_desconhecida_nao_confirma(self):
        r=self.receber(body(mid="wamid.outro"))
        self.assertEqual(r["confirmadas"],0)
        self.assertEqual(r["nao_correspondentes"],1)
        self.assertEqual(self.estado(),"ACCEPTED")

    def test_read_nao_pula_status_accepted(self):
        r=self.receber(body(status="read"))
        self.assertEqual(r["confirmadas"],0)
        self.assertEqual(r["outros_status_sem_promocao"],1)
        self.assertEqual(self.estado(),"ACCEPTED")

    def test_corpo_maior_que_limite_bloqueado(self):
        raw=b"x"*256001
        with self.assertRaises(ErroWebhook):
            verificar_assinatura(raw_body=raw,signature=signature(raw),
                                app_secret=SECRET)

    def test_json_invalido_assinado_falha(self):
        raw=b"not json"
        with self.assertRaises(ErroWebhook):
            self.receber(raw)
        self.assertEqual(self.estado(),"ACCEPTED")

    def test_lista_status_incorreta_falha(self):
        raw=json.dumps({"object":"whatsapp_business_account",
                         "entry":[{"changes":[{
                             "field":"messages",
                             "value":{"statuses":"invalid"}}]}]}).encode()
        with self.assertRaises(ErroWebhook):
            self.receber(raw)

    def test_sem_segredo_valido_falha(self):
        with self.assertRaises(PermissionError):
            aplicar_webhook_entregas(self.db,raw_body=body(),
                   signature=signature(body()),app_secret="abc")

    def test_status_futuro_nao_e_homologado(self):
        with self.assertRaises(ErroWebhook):
            self.receber(body(status="paid_for"))
        self.assertEqual(self.estado(),"ACCEPTED")


if __name__=="__main__":
    unittest.main()
