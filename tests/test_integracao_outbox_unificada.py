"""R08: idempotência cruzada de briefing e WhatsApp, inteiramente offline."""
import hashlib
import hmac
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.entrega_whatsapp import preparar_template
from nivon.outbox_briefing import (
    abrir_outbox, agendar_briefing, reservar_para_entrega,
)
from nivon.outbox_whatsapp import (
    registrar_edicao, despachar_registrado, consultar_envio,
)
from nivon.outbox_unificada import (
    ErroControleEnvio, mensagem_de_prova, registrar_decisao_consentimento,
    verificar_consentimento_pre_post,
)

KEY=b"TESTE-CHAVE-DE-ATESTACAO-EXTERNA-NIVON-NAO-CONTEM-PII-000000"
RECIPIENT_SECRET=b"TESTE-CHAVE-DESTINATARIO-NIVON-UNICA-PARA-DOIS-CANAIS-0000"
PHONE="5566999999999"
DIGEST=hmac.new(RECIPIENT_SECRET,PHONE.encode(),hashlib.sha256).hexdigest()
DATE="2026-10-20"
TS="2026-10-20T08:00:00-03:00"


def evento_consentimento(con, *, action="CONCEDER", evidence="CONSENTIMENTO_FIXTURE_AUDITADO",
                        em="2026-10-20T07:00:00-03:00"):
    sig=hmac.new(KEY,mensagem_de_prova(
        acao=action,destinatario_hmac=DIGEST,evidencia_id=evidence,em=em),
        hashlib.sha256).hexdigest()
    return registrar_decisao_consentimento(
        con,acao=action,destinatario_hmac=DIGEST,
        evidencia_id=evidence,em=em,assinatura=sig,chave_verificacao=KEY,
    )


def modelo(template="nivon_briefing_diario"):
    return preparar_template(
        destino=PHONE,template=template,
        resumo="Resumo inteiramente sintético da soja, fretes e dos portos.",
        link="https://nivon.example/briefings/2026-10-20",
        gerado_em=TS, opt_in_registrado=True, template_aprovado=True,
    )


def agendar(con):
    texto="Resumo sintético do NIVON sem mensagem real."
    return agendar_briefing(
        con, dia_local=DATE, destinatario_hmac=DIGEST,
        briefing={"status":"PREPARADO_SEM_ENVIO","texto":texto,
                  "sha256":hashlib.sha256(texto.encode()).hexdigest()},
        agora=TS,auditoria_aprovada=True,
    )


def enviar(con, item, called):
    return despachar_registrado(
        con,item,autorizar_envio=True,custos_aprovados=True,
        remetente=lambda _: (called.append(True) or
                            {"provider_message_id":"wamid.SYNTHETIC-12345"}),
    )


class TestOutboxUnificada(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.path=Path(self.temp.name)/"single-db.sqlite"
        self.con=abrir_outbox(self.path)
        self.item=modelo()

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def test_sem_consentimento_nenhuma_reserva_ou_post_e_feito(self):
        legacy=agendar(self.con)
        registrar_edicao(self.con,self.item,edicao=DATE,chave_destinatario=RECIPIENT_SECRET)
        with self.assertRaises(PermissionError):
            reservar_para_entrega(self.con,id=legacy["id"])
        calls=[]
        with self.assertRaises(PermissionError):
            enviar(self.con,self.item,calls)
        self.assertEqual(calls,[])
        self.assertEqual(self.con.execute(
            "SELECT status FROM briefing_outbox").fetchone()[0],"PENDING")
        self.assertEqual(consultar_envio(self.con,self.item["idempotency_key"])["tentativas"],0)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM nivon_reservas_canonicas").fetchone()[0],0)

    def test_whatsapp_reserva_primeiro_bloqueia_briefing_legado(self):
        evento_consentimento(self.con)
        antigo=agendar(self.con)
        registrar_edicao(self.con,self.item,edicao=DATE,chave_destinatario=RECIPIENT_SECRET)
        calls=[]
        self.assertEqual(enviar(self.con,self.item,calls)["estado"],"ACEITO_PROVEDOR")
        self.assertEqual(calls,[True])
        with self.assertRaises(ErroControleEnvio):
            reservar_para_entrega(self.con,id=antigo["id"])
        self.assertEqual(self.con.execute(
            "SELECT status FROM briefing_outbox").fetchone()[0],"PENDING")
        row=self.con.execute("SELECT canal FROM nivon_reservas_canonicas").fetchone()
        self.assertEqual(row[0],"WHATSAPP")

    def test_briefing_reserva_primeiro_bloqueia_whatsapp_e_rollback(self):
        evento_consentimento(self.con)
        antigo=agendar(self.con)
        registrar_edicao(self.con,self.item,edicao=DATE,chave_destinatario=RECIPIENT_SECRET)
        reservado=reservar_para_entrega(self.con,id=antigo["id"])
        self.assertEqual(reservado["status"],"RESERVED_SEM_ENVIO")
        calls=[]
        with self.assertRaises(ErroControleEnvio):
            enviar(self.con,self.item,calls)
        self.assertEqual(calls,[])
        self.assertEqual(consultar_envio(self.con,self.item["idempotency_key"])["tentativas"],0)
        self.assertEqual(self.con.execute(
            "SELECT canal FROM nivon_reservas_canonicas").fetchone()[0],"BRIEFING")

    def test_troca_de_template_nao_contorna_reserva_diaria(self):
        evento_consentimento(self.con)
        outro=modelo("nivon_alerta_agro")
        registrar_edicao(self.con,self.item,edicao=DATE,chave_destinatario=RECIPIENT_SECRET)
        registrar_edicao(self.con,outro,edicao=DATE,chave_destinatario=RECIPIENT_SECRET)
        calls=[]
        enviar(self.con,self.item,calls)
        with self.assertRaises(ErroControleEnvio):
            enviar(self.con,outro,calls)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM nivon_reservas_canonicas").fetchone()[0],1)

    def test_revogacao_antes_da_reserva_bloqueia_todos_os_canais(self):
        evento_consentimento(self.con)
        evento_consentimento(self.con,action="REVOGAR",
                            evidence="OPT_OUT_FIXTURE_CONFIRMADO",
                            em="2026-10-20T09:00:00-03:00")
        legacy=agendar(self.con)
        registrar_edicao(self.con,self.item,edicao=DATE,chave_destinatario=RECIPIENT_SECRET)
        with self.assertRaises(PermissionError):
            reservar_para_entrega(self.con,id=legacy["id"])
        calls=[]
        with self.assertRaises(PermissionError):
            enviar(self.con,self.item,calls)
        self.assertEqual(calls,[])
        with self.assertRaises(PermissionError):
            evento_consentimento(self.con,evidence="TENTATIVA_REATIVAR_AUTOMATICAMENTE",
                                em="2026-10-21T08:00:00-03:00")

    def test_revogacao_apos_reserva_bloqueia_pre_post(self):
        evento_consentimento(self.con)
        antigo=agendar(self.con)
        reservar_para_entrega(self.con,id=antigo["id"])
        evento_consentimento(self.con,action="REVOGAR",
                            evidence="OPT_OUT_FIXTURE_APOS_RESERVA",
                            em="2026-10-20T09:00:00-03:00")
        self.assertEqual(self.con.execute(
            "SELECT estado FROM nivon_reservas_canonicas").fetchone()[0],
            "BLOQUEADA_REVOGACAO")
        with self.assertRaises(PermissionError):
            verificar_consentimento_pre_post(
                self.con,dia_local=DATE,destinatario_hmac=DIGEST,
                canal="BRIEFING",intencao_id=str(antigo["id"]))

    def test_assinatura_falsa_nao_cadastra_consentimento(self):
        with self.assertRaises(PermissionError):
            registrar_decisao_consentimento(
                self.con,acao="CONCEDER",destinatario_hmac=DIGEST,
                evidencia_id="ASSINATURA_FALSA_EM_TESTE",em=TS,
                assinatura="0"*64,chave_verificacao=KEY)
        # Uma requisição de agendamento não substitui opt-in assinado.
        legacy=agendar(self.con)
        with self.assertRaises(PermissionError):
            reservar_para_entrega(self.con,id=legacy["id"])

    def test_reabertura_mantem_idempotencia_e_ausencia_de_pii(self):
        evento_consentimento(self.con)
        registrar_edicao(self.con,self.item,edicao=DATE,chave_destinatario=RECIPIENT_SECRET)
        calls=[]
        enviar(self.con,self.item,calls)
        self.con.close()
        self.con=abrir_outbox(self.path)
        legacy=agendar(self.con)
        with self.assertRaises(ErroControleEnvio):
            reservar_para_entrega(self.con,id=legacy["id"])
        raw=self.path.read_bytes()
        self.assertNotIn(PHONE.encode(),raw)
        self.assertNotIn(b"Resumo inteiramente sintetico",raw)

    def test_duas_conexoes_concorrentes_reservam_so_uma(self):
        evento_consentimento(self.con)
        first=agendar(self.con)
        # No arquivo compartilhado, BEGIN IMMEDIATE serializa as reservas.
        def worker(_):
            con=abrir_outbox(self.path)
            try:
                reservado=reservar_para_entrega(con,id=first["id"])
                return reservado["status"]
            except (ErroControleEnvio,ValueError):
                return "BLOCKED"
            finally:
                con.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            res=list(pool.map(worker,range(2)))
        self.assertEqual(sorted(res),["BLOCKED","RESERVED_SEM_ENVIO"])
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM nivon_reservas_canonicas").fetchone()[0],1)


if __name__ == "__main__":
    unittest.main()
