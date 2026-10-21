"""WSGI Meta webhook — testes totalmente locais e sem sockets externos."""
import hashlib
import hmac
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nivon.outbox_unificada import registrar_decisao_consentimento, mensagem_de_prova

from nivon.outbox_briefing import (
    abrir_outbox,agendar_briefing,reservar_para_entrega,registrar_aceite
)
from nivon.webhook_wsgi import app

SECRET="s"*40
VERIFY="verify-only-local-fixture"


def emitir(raw: bytes, *, signed: bool=True, path="/webhooks/whatsapp",
           mime="application/json", method="POST"):
    headers=[]
    def start_response(status,fields):
        headers.append((status,fields))
    env={"PATH_INFO":path,"REQUEST_METHOD":method,"CONTENT_TYPE":mime,
         "CONTENT_LENGTH":str(len(raw)),"wsgi.input":io.BytesIO(raw),
         "QUERY_STRING":""}
    if signed:
        env["HTTP_X_HUB_SIGNATURE_256"]="sha256="+hmac.new(
            SECRET.encode(),raw,hashlib.sha256).hexdigest()
    body=b"".join(app(env,start_response))
    return headers[0][0],body

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


class TestWebhookWSGI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.dbpath=str(Path(self.temp.name)/"outbox.sqlite")
        self.env=patch.dict(os.environ,{
            "NIVON_META_VERIFY_TOKEN":VERIFY,
            "NIVON_META_APP_SECRET":SECRET,
            "NIVON_OUTBOX_PATH":self.dbpath,
        })
        self.env.start()
        db=abrir_outbox(self.dbpath)
        consentir_teste(db,"b"*64,"2026-10-19T12:00:00+00:00")
        texto="conteudo de teste"
        b={"status":"PREPARADO_SEM_ENVIO","texto":texto,
           "sha256":hashlib.sha256(texto.encode()).hexdigest()}
        r=agendar_briefing(db,dia_local="2026-10-19",
           destinatario_hmac="b"*64,briefing=b,
           agora="2026-10-19T12:00:00+00:00",auditoria_aprovada=True)
        reservado=reservar_para_entrega(db,id=r["id"])
        registrar_aceite(db,id=r["id"],token=reservado["token"],
                         provider_message_id="wamid.sintetico")
        db.close()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def event(self,msgid="wamid.sintetico",status="delivered"):
        return json.dumps({"object":"whatsapp_business_account","entry":[{
           "changes":[{"field":"messages","value":{"statuses":[{
             "id":msgid,"status":status,"timestamp":"1792425600"
           }]}}]}]}).encode()

    def estado(self):
        db=abrir_outbox(self.dbpath)
        res=db.execute("SELECT status FROM briefing_outbox").fetchone()[0]
        db.close()
        return res

    def test_get_challenge_valido(self):
        rows=[]
        def sr(status, headers):
            rows.append(status)
        env={"PATH_INFO":"/webhooks/whatsapp","REQUEST_METHOD":"GET",
             "QUERY_STRING":"hub.mode=subscribe&hub.verify_token="+VERIFY+
                            "&hub.challenge=123456"}
        r=b"".join(app(env,sr))
        self.assertEqual(rows[0],"200 OK")
        self.assertEqual(r,b"123456")

    def test_get_challenge_invalido(self):
        rows=[]
        env={"PATH_INFO":"/webhooks/whatsapp","REQUEST_METHOD":"GET",
             "QUERY_STRING":"hub.mode=subscribe&hub.verify_token=errado&hub.challenge=123"}
        r=b"".join(app(env,lambda status,headers:rows.append(status)))
        self.assertEqual(rows[0],"403 Forbidden")

    def test_post_entrega_autenticada(self):
        status,body=emitir(self.event())
        self.assertEqual(status,"200 OK")
        self.assertEqual(self.estado(),"DELIVERED")

    def test_post_assinatura_falsa_bloqueada(self):
        status,body=emitir(self.event(),signed=False)
        self.assertEqual(status,"403 Forbidden")
        self.assertEqual(self.estado(),"ACCEPTED")

    def test_post_id_externo_nao_altera_fila(self):
        status,body=emitir(self.event(msgid="wamid.outro"))
        self.assertEqual(status,"200 OK")
        self.assertEqual(self.estado(),"ACCEPTED")

    def test_post_read_nao_confirma_entrega(self):
        status,body=emitir(self.event(status="read"))
        self.assertEqual(status,"200 OK")
        self.assertEqual(self.estado(),"ACCEPTED")

    def test_mime_nao_json_recusado(self):
        status,_=emitir(self.event(),mime="text/html")
        self.assertEqual(status,"415 Unsupported Media Type")

    def test_path_desconhecido_nao_exposto(self):
        status,_=emitir(self.event(),path="/send")
        self.assertEqual(status,"404 Not Found")

    def test_banco_indisponivel_nao_parece_evento_invalido(self):
        bad_path=str(Path(self.temp.name)/"pasta_inexistente"/"db.sqlite")
        with patch.dict(os.environ,{"NIVON_OUTBOX_PATH":bad_path}):
            status,body=emitir(self.event())
        self.assertEqual(status,"503 Service Unavailable")
        self.assertNotIn(b"pasta_inexistente",body)
        self.assertEqual(self.estado(),"ACCEPTED")

    def test_sem_configuracao_falha_fechada(self):
        with patch.dict(os.environ,{"NIVON_META_APP_SECRET":""}):
            status,_=emitir(self.event())
        self.assertEqual(status,"503 Service Unavailable")


if __name__=="__main__":
    unittest.main()
