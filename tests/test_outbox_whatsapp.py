import hashlib
import hmac
import io
import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from nivon.autorizacao_envio import conteudo_canonico, verificar_autorizacao
from suporte_provas_outbox import provas_sinteticas
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.entrega_whatsapp import preparar_template
from nivon.outbox_whatsapp import (
    ErroOutbox, registrar_edicao, consultar_envio, despachar_registrado,
    aplicar_status_assinado, vincular_ack_verificado,
    registrar_autorizacao, revogar_autorizacao,
)


SEGREDO=b"segredo-unicamente-sintetico-para-testes-de-outbox-000000"
APP_SECRET=b"app-secret-ficticio-de-teste-para-webhook-123456"
CHAVE_AUDITORIA=b"auditor-independente-sintetico-com-mais-de-32-bytes"


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

    def aprovar(self, *, modelo=None, edicao_texto="Briefing NIVON sintético e revisado.",
                **alteracoes):
        modelo = modelo or self.modelo
        raw = edicao_texto.encode("utf-8")
        hash_editorial = hashlib.sha256(raw).hexdigest()
        payload = modelo["payload"]
        fp = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        destinatario = hmac.new(
            SEGREDO, payload["to"].encode(), hashlib.sha256
        ).hexdigest()
        now = datetime.now(timezone.utc)
        doc = {
            "idempotency_key": modelo["idempotency_key"],
            "edicao": "2026-10-20",
            "payload_sha256": fp,
            "sha256_editorial": hash_editorial,
            "destinatario_hmac": destinatario,
            "revisao_editorial_id": "REVISAO_SINTETICA_001",
            "direitos_publicacao_id": "DIREITOS_SINTETICOS_001",
            "consentimento_id": "CONSENTIMENTO_SINTETICO_001",
            "template_aprovado_id": "TEMPLATE_SINTETICO_001",
            "orcamento_id": "ORCAMENTO_SINTETICO_001",
            "aprovador_id": "AUDITOR_SINTETICO_INDEPENDENTE",
            "emitido_em": (now - timedelta(minutes=1)).isoformat(),
            "valido_ate": (now + timedelta(hours=1)).isoformat(),
            "revisao_independente": True,
            "direitos_publicacao": True,
            "consentimento_ativo": True,
            "template_aprovado": True,
            "orcamento_aprovado": True,
            "revogado": False,
        }
        doc.update(alteracoes)
        assinatura = "sha256=" + hmac.new(
            CHAVE_AUDITORIA, conteudo_canonico(doc), hashlib.sha256
        ).hexdigest()
        editorial = {
            "estado": "EDICAO_OFFLINE_PREPARADA_SEM_ENVIO",
            "enviado": False,
            "texto": edicao_texto,
            "sha256": hash_editorial,
            "preflight_editorial": {
                "apto_revisao": True, "bloqueios": [],
                "sha256_texto": hash_editorial, "modo": "OFFLINE_SEM_ENVIO"
            }
        }
        self.documento = doc
        self.assinatura = assinatura
        self.comprovantes, self.emissores = provas_sinteticas(doc)
        return registrar_autorizacao(
            self.con, modelo, edicao_editorial=editorial,
            documento=doc, assinatura=assinatura,
            chave_auditoria=CHAVE_AUDITORIA,
            comprovantes=self.comprovantes, emissores=self.emissores,
        )

    def despachar(self, remetente):
        return despachar_registrado(
            self.con, self.modelo, autorizar_envio=True,
            custos_aprovados=True, remetente=remetente,
            documento=self.documento, assinatura=self.assinatura,
            chave_auditoria=CHAVE_AUDITORIA,
            comprovantes=self.comprovantes, emissores=self.emissores,
        )

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
        self.aprovar()
        observado=[]
        def fake(p):
            observado.append(consultar_envio(self.con,p["idempotency_key"])["estado"])
            return {"provider_message_id":"wamid.123456"}
        r=self.despachar(fake)
        self.assertEqual(observado,["ENVIO_INDETERMINADO"])
        self.assertEqual(r["estado"],"ACEITO_PROVEDOR")
        self.assertEqual(consultar_envio(self.con,r["chave"])["tentativas"],1)
        with self.assertRaises(ErroOutbox):
            self.despachar(lambda p:self.fail("não repetir POST"))

    def test_timeout_nao_permite_reenviar(self):
        self.registrar()
        self.aprovar()
        def timeout(_):
            raise TimeoutError("tempo excedido")
        r=self.despachar(timeout)
        self.assertEqual(r["estado"],"ENVIO_INDETERMINADO")
        self.con.close()
        self.con=sqlite3.connect(self.path)
        with self.assertRaises(ErroOutbox):
            self.despachar(lambda p:self.fail("duplicou após reinicialização"))

    def test_status_assinados_e_fora_de_ordem(self):
        self.registrar()
        self.aprovar()
        self.despachar(lambda p:{"provider_message_id":"wamid.123456"})
        self.assertEqual(self.webhook("sent")["atualizados"],1)
        self.assertEqual(self.webhook("delivered")["atualizados"],1)
        self.assertEqual(self.webhook("read")["atualizados"],1)
        self.assertEqual(self.webhook("delivered")["atualizados"],0)
        self.assertEqual(self.webhook("failed")["atualizados"],0)
        self.assertEqual(consultar_envio(self.con,self.modelo["idempotency_key"])["estado"],"LIDO")

    def test_falha_provider_e_estado_terminal(self):
        self.registrar()
        self.aprovar()
        self.despachar(lambda p:{"provider_message_id":"wamid.123456"})
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
        self.aprovar()
        self.despachar(lambda p:{"provider_message_id":"wamid.123456"})
        result=self.webhook("delivered",wid="wamid.UNRELATED")
        self.assertEqual(result["atualizados"],0)
        self.assertEqual(result["ignorados_ou_sem_correspondencia"],1)

    def test_conciliacao_manual_exige_evidencia(self):
        self.registrar()
        self.aprovar()
        self.despachar(lambda p:(_ for _ in ()).throw(TimeoutError()))
        with self.assertRaises(ErroOutbox):
            vincular_ack_verificado(self.con,chave=self.modelo["idempotency_key"],
                                    provider_message_id="wamid.123456",evidencia_conciliacao="x")
        vincular_ack_verificado(self.con,chave=self.modelo["idempotency_key"],
                                provider_message_id="wamid.123456",
                                evidencia_conciliacao="CONFERENCIA_MANUAL_20261020")
        self.assertEqual(self.webhook("delivered")["atualizados"],1)
        self.assertEqual(consultar_envio(self.con,self.modelo["idempotency_key"])["estado"],"ENTREGUE")

    def test_sem_aprovacao_persistida_nao_chama_remetente(self):
        self.registrar()
        chamadas = []
        with self.assertRaisesRegex(PermissionError, "autorização"):
            despachar_registrado(
                self.con, self.modelo, autorizar_envio=True,
                custos_aprovados=True,
                remetente=lambda *_: chamadas.append(True),
            )
        self.assertEqual(chamadas, [])
        self.assertEqual(consultar_envio(
            self.con, self.modelo["idempotency_key"])["tentativas"], 0)

    def test_documento_de_outra_edicao_nao_gera_aprovacao(self):
        self.registrar()
        with self.assertRaisesRegex(ErroOutbox, "não corresponde"):
            self.aprovar(edicao="2026-10-21")
        linhas = self.con.execute("SELECT count(*) FROM nivon_autorizacoes").fetchone()[0]
        self.assertEqual(linhas, 0)

    def test_assinatura_alterada_ou_chave_diferente_bloqueia(self):
        self.registrar()
        self.aprovar()
        chamadas = []
        antiga = self.assinatura
        self.assinatura = "sha256=" + "0"*64
        with self.assertRaisesRegex(PermissionError, "assinatura"):
            self.despachar(lambda *_: chamadas.append(True))
        self.assinatura = antiga
        self.documento = dict(self.documento, consentimento_id="CONSENTIMENTO_TROCADO_1234")
        with self.assertRaisesRegex(PermissionError, "assinatura"):
            self.despachar(lambda *_: chamadas.append(True))
        self.assertEqual(chamadas, [])
        self.assertEqual(consultar_envio(
            self.con, self.modelo["idempotency_key"])["tentativas"], 0)

    def test_editorial_com_hash_divergente_nao_registra(self):
        self.registrar()
        doc = self.aprovar()
        self.assertEqual(doc["estado"], "AUTORIZACAO_REGISTRADA_SEM_ENVIO")
        self.assertEqual(self.con.execute(
            "SELECT count(*) FROM nivon_autorizacoes").fetchone()[0], 1)
        # O conteúdo assinado é imutável: uma segunda revisão precisa de uma nova
        # edição/versão e não deve sobrescrever a autorização anterior.
        with self.assertRaisesRegex(ErroOutbox, "edição editorial diverge"):
            self.aprovar(edicao_texto="Texto corrigido, sem novo SHA da aprovação",
                         sha256_editorial="a"*64)

    def test_revogacao_bloqueia_antes_da_reserva(self):
        self.registrar()
        self.aprovar()
        resultado = revogar_autorizacao(
            self.con, chave=self.modelo["idempotency_key"],
            evidencia_revogacao="OPT_OUT_DOCUMENTADO_20261020",
        )
        self.assertEqual(resultado["estado"], "AUTORIZACAO_REVOGADA")
        prova = self.con.execute(
            "SELECT evidencia_sha256 FROM nivon_revogacoes WHERE idempotency_key=?",
            (self.modelo["idempotency_key"],)).fetchone()
        self.assertEqual(prova[0], hashlib.sha256(
            b"OPT_OUT_DOCUMENTADO_20261020").hexdigest())
        self.assertNotIn(b"OPT_OUT_DOCUMENTADO_20261020", self.path.read_bytes())
        chamadas = []
        with self.assertRaisesRegex(PermissionError, "revogada"):
            self.despachar(lambda *_: chamadas.append(True))
        self.assertEqual(chamadas, [])
        self.assertEqual(consultar_envio(
            self.con, self.modelo["idempotency_key"])["tentativas"], 0)
        with self.assertRaises(ErroOutbox):
            self.aprovar()  # revogação desta edição não é substituída

    def test_revogacao_editorial_nao_equivale_a_optout_global(self):
        self.registrar()
        self.aprovar()
        revogar_autorizacao(
            self.con, chave=self.modelo["idempotency_key"],
            evidencia_revogacao="REVISAO_CORRIGIDA_20261020")
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM nivon_optouts_destinatario").fetchone()[0],
            0,
        )
        segundo = preparar_template(
            destino="5566999999999", template="nivon_briefing_diario",
            resumo="Outra edição sintética sem opt-out registrado.",
            link="https://nivon.example/briefings/2026-10-21",
            gerado_em="2026-10-21T07:00:00-03:00",
            opt_in_registrado=True, template_aprovado=True)
        r = registrar_edicao(
            self.con, segundo, edicao="2026-10-21", chave_destinatario=SEGREDO)
        self.assertEqual(r["estado"], "PREPARADO")
        # A nova edição ainda precisa de autorização independente própria.

    def test_revogacao_preservada_apos_reabrir_sqlite(self):
        self.registrar()
        self.aprovar()
        chave = self.modelo["idempotency_key"]
        revogar_autorizacao(self.con, chave=chave,
                            evidencia_revogacao="OPT_OUT_MUNICIPAL_20261020")
        self.con.close()
        self.con = sqlite3.connect(self.path)
        self.assertEqual(self.con.execute(
            "SELECT count(*) FROM nivon_revogacoes WHERE idempotency_key=?",
            (chave,)).fetchone()[0], 1)
        with self.assertRaises(PermissionError):
            self.despachar(lambda *_: self.fail("não chamar envio após restart e revogação"))
        self.assertEqual(consultar_envio(self.con, chave)["tentativas"], 0)

    def test_consentimento_desativado_reprova_mesmo_assinado(self):
        self.registrar()
        with self.assertRaisesRegex(PermissionError, "consentimento"):
            self.aprovar(consentimento_ativo=False)
        self.assertEqual(self.con.execute(
            "SELECT count(*) FROM nivon_autorizacoes").fetchone()[0], 0)

    def test_aprovacao_expirada_reprova(self):
        self.registrar()
        ontem = datetime.now(timezone.utc) - timedelta(days=3)
        with self.assertRaisesRegex(PermissionError, "expirada"):
            self.aprovar(emitido_em=ontem.isoformat(),
                         valido_ate=(ontem + timedelta(hours=1)).isoformat())
        self.assertEqual(self.con.execute(
            "SELECT count(*) FROM nivon_autorizacoes").fetchone()[0], 0)

    def test_recuperacao_crash_apos_reserva_nao_duplica(self):
        self.registrar()
        self.aprovar()
        eventos = []
        def falha_apos_reserva(preparado):
            estado = consultar_envio(self.con, preparado["idempotency_key"])["estado"]
            eventos.append(estado)
            raise RuntimeError("processo caiu depois da reserva")
        resultado = self.despachar(falha_apos_reserva)
        self.assertEqual(eventos, ["ENVIO_INDETERMINADO"])
        self.assertEqual(resultado["estado"], "ENVIO_INDETERMINADO")
        self.con.close()
        self.con = sqlite3.connect(self.path)
        with self.assertRaises(ErroOutbox):
            self.despachar(lambda *_: self.fail("POST duplicado no replay"))
        self.assertEqual(consultar_envio(
            self.con, self.modelo["idempotency_key"])["tentativas"], 1)

    def test_nao_persiste_destino_ou_texto_no_banco(self):
        self.registrar()
        blob=self.path.read_bytes()
        self.assertNotIn(b"5566999999999",blob)
        self.assertNotIn(b"Nivon: cen",blob)
        self.assertNotIn(b"nivon.example",blob)


if __name__=="__main__":
    unittest.main()
