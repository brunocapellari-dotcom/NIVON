import hashlib
import hmac
import io
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.entrega_whatsapp import preparar_template
from nivon.outbox_whatsapp import (
    ErroOutbox, registrar_edicao, consultar_envio, despachar_registrado,
    aplicar_status_assinado, vincular_ack_verificado,
)


SEGREDO=b"segredo-unicamente-sintetico-para-testes-de-outbox-000000"
APP_SECRET=b"app-secret-ficticio-de-teste-para-webhook-123456"


class TestOutboxWhatsApp(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.path=Path(self.temp.name)/"outbox.sqlite"
        self.con=sqlite3.connect(self.path)
        self.modelo=preparar_template(
            destino="5566999999999",template="nivon_briefing_diario",
            resumo="Nivon: cenário da soja e dos portos atualizado.",
            link="https://nivon.example/briefings/2026-10-20",
            gerado_em="2026-10-20T07:00:00-03:00",
            opt_in_registrado=True,template_aprovado=True,
        )

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def registrar(self, modelo=None):
        return registrar_edicao(self.con,modelo or self.modelo,edicao="2026-10-20",
                               chave_destinatario=SEGREDO)

    def webhook(self, status, wid="wamid.123456"):
        payload={"object":"whatsapp_business_account",
                 "entry":[{"id":"TEST_WABA","changes":[{"field":"messages",
                           "value":{"statuses":[{"id":wid,"status":status,
                                                   "timestamp":"1792502400"}]}}]}]}
        raw=json.dumps(payload).encode("utf-8")
        signature="sha256="+hmac.new(APP_SECRET,raw,hashlib.sha256).hexdigest()
        return aplicar_status_assinado(self.con,corpo=raw,assinatura=signature,
                                      app_secret=APP_SECRET)

    def test_registro_idempotente_mesma_edicao(self):
        a=self.registrar()
        b=self.registrar()
        self.assertEqual(a["chave"],b["chave"])
        self.assertFalse(a["ja_existia"])
        self.assertTrue(b["ja_existia"])
        self.assertEqual(consultar_envio(self.con,a["chave"])["tentativas"],0)

    def test_correcoes_na_mesma_edicao_exigem_revisao(self):
        self.registrar()
        outro=preparar_template(
            destino="5566999999999",template="nivon_briefing_diario",
            resumo="Outro relatório corrigido mas mesma edição.",
            link="https://nivon.example/briefings/2026-10-20-v2",
            gerado_em="2026-10-20T07:00:00-03:00",
            opt_in_registrado=True,template_aprovado=True)
        with self.assertRaises(ErroOutbox):
            self.registrar(outro)

    def test_permissao_nao_envia(self):
        self.registrar()
        chamado=[]
        with self.assertRaises(PermissionError):
            despachar_registrado(self.con,self.modelo,remetente=lambda x:chamado.append(True))
        self.assertFalse(chamado)
        self.assertEqual(consultar_envio(self.con,self.modelo["idempotency_key"])["tentativas"],0)

    def test_reserva_antes_do_post_e_sem_duplicacao(self):
        self.registrar()
        observado=[]
        def fake(p):
            observado.append(consultar_envio(self.con,p["idempotency_key"])["estado"])
            return {"provider_message_id":"wamid.123456"}
        r=despachar_registrado(self.con,self.modelo,autorizar_envio=True,
                              custos_aprovados=True,remetente=fake)
        self.assertEqual(observado,["ENVIO_INDETERMINADO"])
        self.assertEqual(r["estado"],"ACEITO_PROVEDOR")
        self.assertEqual(consultar_envio(self.con,r["chave"])["tentativas"],1)
        with self.assertRaises(ErroOutbox):
            despachar_registrado(self.con,self.modelo,autorizar_envio=True,
                                 custos_aprovados=True,
                                 remetente=lambda p:self.fail("não repetir POST"))

    def test_timeout_nao_permite_reenviar(self):
        self.registrar()
        def timeout(_):
            raise TimeoutError("tempo excedido")
        r=despachar_registrado(self.con,self.modelo,autorizar_envio=True,
                              custos_aprovados=True,remetente=timeout)
        self.assertEqual(r["estado"],"ENVIO_INDETERMINADO")
        self.con.close()
        self.con=sqlite3.connect(self.path)
        with self.assertRaises(ErroOutbox):
            despachar_registrado(self.con,self.modelo,autorizar_envio=True,
                                 custos_aprovados=True,
                                 remetente=lambda p:self.fail("duplicou após reinicialização"))

    def test_status_assinados_e_fora_de_ordem(self):
        self.registrar()
        despachar_registrado(self.con,self.modelo,autorizar_envio=True,
                             custos_aprovados=True,
                             remetente=lambda p:{"provider_message_id":"wamid.123456"})
        self.assertEqual(self.webhook("sent")["atualizados"],1)
        self.assertEqual(self.webhook("delivered")["atualizados"],1)
        self.assertEqual(self.webhook("read")["atualizados"],1)
        self.assertEqual(self.webhook("delivered")["atualizados"],0)
        self.assertEqual(self.webhook("failed")["atualizados"],0)
        self.assertEqual(consultar_envio(self.con,self.modelo["idempotency_key"])["estado"],"LIDO")

    def test_falha_provider_e_estado_terminal(self):
        self.registrar()
        despachar_registrado(self.con,self.modelo,autorizar_envio=True,
                             custos_aprovados=True,
                             remetente=lambda p:{"provider_message_id":"wamid.123456"})
        self.webhook("failed")
        self.assertEqual(consultar_envio(self.con,self.modelo["idempotency_key"])["estado"],"FALHOU")
        self.assertEqual(self.webhook("delivered")["atualizados"],0)

    def test_webhook_nao_assinado_nao_altera(self):
        self.registrar()
        raw=b'{"object":"whatsapp_business_account"}'
        with self.assertRaises(PermissionError):
            aplicar_status_assinado(self.con,corpo=raw,assinatura="sha256"+"0"*64,
                                    app_secret=APP_SECRET)
        self.assertEqual(consultar_envio(self.con,self.modelo["idempotency_key"])["estado"],"PREPARADO")

    def test_webhook_de_outro_numero_nao_altera(self):
        self.registrar()
        despachar_registrado(self.con,self.modelo,autorizar_envio=True,
                             custos_aprovados=True,
                             remetente=lambda p:{"provider_message_id":"wamid.123456"})
        result=self.webhook("delivered",wid="wamid.UNRELATED")
        self.assertEqual(result["atualizados"],0)
        self.assertEqual(result["ignorados_ou_sem_correspondencia"],1)

    def test_conciliacao_manual_exige_evidencia(self):
        self.registrar()
        despachar_registrado(self.con,self.modelo,autorizar_envio=True,
                             custos_aprovados=True,
                             remetente=lambda p:(_ for _ in ()).throw(TimeoutError()))
        with self.assertRaises(ErroOutbox):
            vincular_ack_verificado(self.con,chave=self.modelo["idempotency_key"],
                                    provider_message_id="wamid.123456",evidencia_conciliacao="x")
        vincular_ack_verificado(self.con,chave=self.modelo["idempotency_key"],
                                provider_message_id="wamid.123456",
                                evidencia_conciliacao="CONFERENCIA_MANUAL_20261020")
        self.assertEqual(self.webhook("delivered")["atualizados"],1)
        self.assertEqual(consultar_envio(self.con,self.modelo["idempotency_key"])["estado"],"ENTREGUE")

    def test_nao_persiste_destino_ou_texto_no_banco(self):
        self.registrar()
        blob=self.path.read_bytes()
        self.assertNotIn(b"5566999999999",blob)
        self.assertNotIn(b"Nivon: cen",blob)
        self.assertNotIn(b"nivon.example",blob)


if __name__=="__main__":
    unittest.main()
