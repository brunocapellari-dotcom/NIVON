"""R09: ACK, Meta webhook e reconciliação de dois canais em SQLite offline."""
import hashlib
import hmac
import json
import sqlite3
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from nivon.outbox_briefing import (
    abrir_outbox, agendar_briefing, reservar_para_entrega,
    registrar_aceite, confirmar_entrega,
)
from nivon.outbox_whatsapp import (
    registrar_edicao, despachar_registrado, aplicar_status_assinado,
    consultar_envio, vincular_ack_verificado,
)
from nivon.outbox_recibos import (
    consultar_recibo, vincular_aceite_na_transacao, preparar_recibos,
)
from nivon.outbox_unificada import (
    ErroControleEnvio, mensagem_de_prova, registrar_decisao_consentimento,
)
from nivon.whatsapp_webhook import aplicar_webhook_entregas
from nivon.entrega_whatsapp import preparar_template

STAMP="2026-10-20T12:00:00+00:00"
EDICAO="2026-10-20"
PHONE="5566999999999"
KEY=b"NIVON-CONSENT-TEST-SYNTHETIC-NEVER-PRODUCTION-00000000000"
RECIPIENT_KEY=b"NIVON-RECIPIENT-TEST-SYNTHETIC-NEVER-PRODUCTION-000000"
META_BYTES=b"NIVON-META-SIGNATURE-TEST-NOT-PROD-123456"
META_STR=META_BYTES.decode()


def consentir(db, digest):
    ref="CONSENT-R09-TEST-SINTETICO"
    proof=mensagem_de_prova(acao="CONCEDER", destinatario_hmac=digest,
                          evidencia_id=ref,em=STAMP)
    sig=hmac.new(KEY,proof,hashlib.sha256).hexdigest()
    registrar_decisao_consentimento(
        db,acao="CONCEDER",destinatario_hmac=digest,evidencia_id=ref,
        em=STAMP,assinatura=sig,chave_verificacao=KEY,
    )


def raw_meta(pid, status):
    return json.dumps({"object":"whatsapp_business_account","entry":[{
        "changes":[{"field":"messages","value":{"statuses":[{
            "id":pid,"status":status,"timestamp":"1792502400",
        }]}}]
    }]},separators=(",",":")).encode()


def sig_meta(raw):
    return "sha256="+hmac.new(META_BYTES,raw,hashlib.sha256).hexdigest()


class TestRecibosCanonicos(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.db=abrir_outbox(Path(self.tmp.name)/"outbox.sqlite")
        self.digest=hmac.new(RECIPIENT_KEY,PHONE.encode(),hashlib.sha256).hexdigest()
        consentir(self.db,self.digest)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def briefing(self):
        texto="Briefing sintético de teste de estados e recibos."
        created=agendar_briefing(
            self.db,dia_local=EDICAO,destinatario_hmac=self.digest,
            briefing={"status":"PREPARADO_SEM_ENVIO","texto":texto,
                      "sha256":hashlib.sha256(texto.encode()).hexdigest()},
            agora=STAMP,auditoria_aprovada=True,
        )
        slot=reservar_para_entrega(self.db,id=created["id"])
        registrar_aceite(
            self.db,id=created["id"],token=slot["token"],
            provider_message_id="wamid.BRIEFING-R09",
        )
        return created["id"]

    def whatsapp(self, pid="wamid.WHATSAPP-R09", timeout=False):
        item=preparar_template(
            destino=PHONE,template="nivon_briefing_diario",
            resumo="Mensagem de teste sobre portos e soja, sem rede externa.",
            link="https://nivon.example/r09",
            gerado_em=STAMP,opt_in_registrado=True,template_aprovado=True,
        )
        registrar_edicao(self.db,item,edicao=EDICAO,chave_destinatario=RECIPIENT_KEY)
        if timeout:
            result=despachar_registrado(
                self.db,item,autorizar_envio=True,custos_aprovados=True,
                remetente=lambda _: (_ for _ in ()).throw(TimeoutError("mock")),
            )
        else:
            result=despachar_registrado(
                self.db,item,autorizar_envio=True,custos_aprovados=True,
                remetente=lambda _: {"provider_message_id":pid},
            )
        return item,result

    def meta_whatsapp(self, pid, status):
        body=raw_meta(pid,status)
        return aplicar_status_assinado(
            self.db,corpo=body,assinatura=sig_meta(body),app_secret=META_BYTES,
        )

    def meta_briefing(self, pid="wamid.BRIEFING-R09", status="delivered"):
        body=raw_meta(pid,status)
        return aplicar_webhook_entregas(
            self.db,raw_body=body,signature=sig_meta(body),
            app_secret=META_STR,
        )

    def test_briefing_ack_e_delivery_compartilham_ledger(self):
        self.briefing()
        snap=consultar_recibo(self.db,provider_message_id="wamid.BRIEFING-R09")
        self.assertEqual((snap["canal"],snap["estado"]),("BRIEFING","ACEITO_PROVEDOR"))
        result=self.meta_briefing()
        self.assertEqual(result["confirmadas"],1)
        snap=consultar_recibo(self.db,provider_message_id="wamid.BRIEFING-R09")
        self.assertEqual(snap["estado"],"ENTREGUE")
        self.assertIsNotNone(snap["entregue_utc"])
        self.assertEqual(self.meta_briefing()["confirmadas"],0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_eventos_recibo").fetchone()[0],2)
        self.assertEqual(self.db.execute(
            "SELECT status FROM briefing_outbox").fetchone()[0],"DELIVERED")

    def test_whatsapp_sent_delivered_read_e_replay(self):
        item,res=self.whatsapp()
        self.assertEqual(res["estado"],"ACEITO_PROVEDOR")
        pid="wamid.WHATSAPP-R09"
        self.assertEqual(self.meta_whatsapp(pid,"sent")["atualizados"],1)
        self.assertEqual(consultar_recibo(self.db,provider_message_id=pid)["estado"],"ENVIADO")
        self.assertEqual(self.meta_whatsapp(pid,"delivered")["atualizados"],1)
        self.assertEqual(self.meta_whatsapp(pid,"read")["atualizados"],1)
        self.assertEqual(self.meta_whatsapp(pid,"sent")["atualizados"],0)
        self.assertEqual(self.meta_whatsapp(pid,"failed")["atualizados"],0)
        self.assertEqual(self.meta_whatsapp(pid,"read")["atualizados"],0)
        snap=consultar_recibo(self.db,provider_message_id=pid)
        self.assertEqual(snap["estado"],"LIDO")
        self.assertIsNotNone(snap["entregue_utc"])
        self.assertEqual(consultar_envio(self.db,item["idempotency_key"])["estado"],"LIDO")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_eventos_recibo").fetchone()[0],4)

    def test_whatsapp_failed_e_terminal(self):
        self.whatsapp()
        self.assertEqual(self.meta_whatsapp("wamid.WHATSAPP-R09","failed")["atualizados"],1)
        self.assertEqual(self.meta_whatsapp("wamid.WHATSAPP-R09","delivered")["atualizados"],0)
        self.assertEqual(consultar_recibo(self.db,provider_message_id="wamid.WHATSAPP-R09")["estado"],"FALHOU")

    def test_meta_assinatura_invalida_nao_muda_estado(self):
        self.whatsapp()
        raw=raw_meta("wamid.WHATSAPP-R09","delivered")
        with self.assertRaises(PermissionError):
            aplicar_status_assinado(
                self.db,corpo=raw,assinatura="sha256"+"0"*64,
                app_secret=META_BYTES,
            )
        self.assertEqual(consultar_recibo(self.db,provider_message_id="wamid.WHATSAPP-R09")["estado"],"ACEITO_PROVEDOR")

    def test_recibo_de_provedor_desconhecido_ignorado(self):
        self.whatsapp()
        self.assertEqual(self.meta_whatsapp("wamid.ESTRANHO","delivered")["atualizados"],0)
        with self.assertRaises(ErroControleEnvio):
            consultar_recibo(self.db,provider_message_id="wamid.ESTRANHO")

    def test_aceite_de_outro_id_na_mesma_reserva_negado(self):
        self.briefing()
        preparar_recibos(self.db)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(ErroControleEnvio):
                vincular_aceite_na_transacao(
                    self.db,canal="BRIEFING",intencao_id="1",
                    provider_message_id="wamid.SEGUNDO",quando=STAMP,
                )
        finally:
            self.db.rollback()
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_recibos_canonicos").fetchone()[0],1)

    def test_aceite_sem_reserva_canonica_negado(self):
        preparar_recibos(self.db)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(ErroControleEnvio):
                vincular_aceite_na_transacao(
                    self.db,canal="BRIEFING",intencao_id="ID-SEM-RESERVA",
                    provider_message_id="wamid.ALEATORIO",quando=STAMP,
                )
        finally:
            self.db.rollback()

    def test_conciliacao_manual_de_timeout_cria_aceite_nao_delivery(self):
        item,r=self.whatsapp(timeout=True)
        self.assertEqual(r["estado"],"ENVIO_INDETERMINADO")
        with self.assertRaises(ErroControleEnvio):
            consultar_recibo(self.db,provider_message_id="wamid.TIMEOUT-MANUAL")
        vincular_ack_verificado(
            self.db,chave=item["idempotency_key"],
            provider_message_id="wamid.TIMEOUT-MANUAL",
            evidencia_conciliacao="PROVA_MANUAL_SINTETICA_R09",
        )
        self.assertEqual(consultar_recibo(self.db,provider_message_id="wamid.TIMEOUT-MANUAL")["estado"],"ACEITO_PROVEDOR")
        self.assertEqual(self.meta_whatsapp("wamid.TIMEOUT-MANUAL","delivered")["atualizados"],1)

    def test_mesmo_id_provedor_para_outro_destinatario_reverte_aceite(self):
        self.briefing()
        outro_digest="b"*64
        consentir(self.db,outro_digest)
        texto="Segundo boletim inteiramente sintetico"
        ag=agendar_briefing(
            self.db,dia_local=EDICAO,destinatario_hmac=outro_digest,
            briefing={"status":"PREPARADO_SEM_ENVIO","texto":texto,
                      "sha256":hashlib.sha256(texto.encode()).hexdigest()},
            agora=STAMP,auditoria_aprovada=True,
        )
        reservado=reservar_para_entrega(self.db,id=ag["id"])
        with self.assertRaisesRegex(ValueError, "identificador do provedor") :
            registrar_aceite(
                self.db,id=ag["id"],token=reservado["token"],
                provider_message_id="wamid.BRIEFING-R09",
            )
        self.assertEqual(self.db.execute(
            "SELECT status FROM briefing_outbox WHERE id=?",
            (ag["id"],)).fetchone()[0],"RESERVED")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_recibos_canonicos").fetchone()[0],1)

    def test_falta_recibo_canonico_reverte_webhook_whatsapp(self):
        item,_=self.whatsapp()
        pid="wamid.WHATSAPP-R09"
        self.db.execute("DELETE FROM nivon_eventos_recibo")
        self.db.execute("DELETE FROM nivon_recibos_canonicos")
        self.db.commit()
        with self.assertRaises(ValueError):
            self.meta_whatsapp(pid,"delivered")
        self.assertEqual(
            consultar_envio(self.db,item["idempotency_key"])["estado"],
            "ACEITO_PROVEDOR",
        )
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_eventos_recibo").fetchone()[0],0)

    def test_revogacao_de_consentimento_nao_apaga_recibo_ja_emitido(self):
        item,_=self.whatsapp()
        evidence="REVO-R09-TEST-SINTETICO"
        em="2026-10-21T12:00:00+00:00"
        proof=mensagem_de_prova(
            acao="REVOGAR", destinatario_hmac=self.digest,
            evidencia_id=evidence,em=em)
        sig=hmac.new(KEY,proof,hashlib.sha256).hexdigest()
        registrar_decisao_consentimento(
            self.db,acao="REVOGAR",destinatario_hmac=self.digest,
            evidencia_id=evidence,em=em,assinatura=sig,
            chave_verificacao=KEY,
        )
        self.assertEqual(self.db.execute(
            "SELECT estado FROM nivon_reservas_canonicas").fetchone()[0],
            "BLOQUEADA_REVOGACAO",
        )
        self.assertEqual(self.meta_whatsapp(
            "wamid.WHATSAPP-R09","delivered")["atualizados"],1)
        self.assertEqual(consultar_recibo(
            self.db,provider_message_id="wamid.WHATSAPP-R09")["estado"],
            "ENTREGUE",
        )
        self.assertEqual(self.db.execute(
            "SELECT estado FROM nivon_consentimentos").fetchone()[0],
            "REVOGADO",
        )

    def test_nao_vaza_telefone_nem_corpo_para_ledger(self):
        self.whatsapp()
        raw=Path(self.tmp.name,"outbox.sqlite").read_bytes()
        self.assertNotIn(PHONE.encode(),raw)
        self.assertNotIn(b"Mensagem de teste sobre portos",raw)


if __name__ == "__main__":
    unittest.main()
