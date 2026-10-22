"""Regressões adversariais dos cinco comprovantes offline.

As chaves de teste NÃO representam autoridade real nem acesso Meta.
"""
import copy
import hashlib
import hmac
import json
import unittest
from datetime import datetime, timedelta, timezone

from nivon.outbox_whatsapp import (
    registrar_autorizacao, consultar_envio, ErroOutbox,
)
from nivon.provas_externas_envio import (
    canonicalizar_prova, verificar_pacote_externo, ErroProvaExterna,
)


class TestCincoProvasIndependentes(unittest.TestCase):
    def setUp(self):
        from test_outbox_whatsapp import TestOutboxWhatsApp
        self.f = TestOutboxWhatsApp(methodName="test_registro_idempotente_mesma_edicao")
        self.f.setUp()
        self.f.registrar()
        self.f.aprovar()

    def tearDown(self):
        self.f.tearDown()

    def _assinar(self, indice):
        reg = self.f.comprovantes[indice]
        chave = self.f.emissores[reg["emissor_id"]]["chave"]
        payload = {k:v for k,v in reg.items() if k != "assinatura"}
        reg["assinatura"] = "sha256=" + hmac.new(
            chave, canonicalizar_prova(payload), hashlib.sha256).hexdigest()

    def _nao_despacha(self):
        chamadas = []
        with self.assertRaises((ErroProvaExterna, PermissionError, ErroOutbox)):
            self.f.despachar(lambda *_: chamadas.append(True))
        self.assertEqual(chamadas, [])
        self.assertEqual(consultar_envio(
            self.f.con, self.f.modelo["idempotency_key"])["tentativas"], 0)

    def test_emissor_desativado_posteriormente_bloqueia_reserva(self):
        emissor = self.f.comprovantes[0]["emissor_id"]
        self.f.emissores[emissor]["ativo"] = False
        self._nao_despacha()

    def test_qualquer_comprovante_removido_ou_duplicado(self):
        self.f.comprovantes.pop()
        self._nao_despacha()
        self.f.comprovantes.append(copy.deepcopy(self.f.comprovantes[0]))
        self._nao_despacha()

    def test_assinatura_adulterada(self):
        self.f.comprovantes[0]["assinatura"] = "sha256=" + "a"*64
        self._nao_despacha()

    def test_comprovante_revogado_mesmo_com_assinatura_valida(self):
        self.f.comprovantes[2]["estado"] = "REVOGADA"
        self._assinar(2)
        self._nao_despacha()

    def test_outro_destinatario_com_assinatura_valida(self):
        self.f.comprovantes[2]["destinatario_hmac"] = "a"*64
        self._assinar(2)
        self._nao_despacha()

    def test_prova_trocada_depois_da_aprovacao_armazenada(self):
        # Mesmo emissor e escopo, mas outro conjunto legitimamente assinado:
        # a revisão registrada era da edição anterior do pacote de provas.
        self.f.comprovantes[1]["emitido_em"] = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).isoformat()
        self._assinar(1)
        self._nao_despacha()
        self.assertEqual(self.f.con.execute(
            "SELECT count(*) FROM nivon_provas_externas").fetchone()[0], 1)

    def test_duas_assinaturas_mesma_chave_violam_independencia(self):
        primeira = self.f.comprovantes[0]
        segunda = self.f.comprovantes[1]
        self.f.emissores[segunda["emissor_id"]]["chave"] = self.f.emissores[
            primeira["emissor_id"]]["chave"]
        self._assinar(1)
        self._nao_despacha()

    def test_emissor_usando_chave_do_aprovador_nao_independente(self):
        emissor = self.f.comprovantes[0]["emissor_id"]
        from test_outbox_whatsapp import CHAVE_AUDITORIA
        self.f.emissores[emissor]["chave"] = CHAVE_AUDITORIA
        self._assinar(0)
        self._nao_despacha()

    def test_prova_futura_e_vencida_nao_valem(self):
        original=copy.deepcopy(self.f.comprovantes[0])
        self.f.comprovantes[0]["emitido_em"] = (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat()
        self._assinar(0)
        self._nao_despacha()
        self.f.comprovantes[0] = original
        self.f.comprovantes[0]["valido_ate"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        self._assinar(0)
        self._nao_despacha()

    def test_registro_sem_prova_externa_nao_persiste(self):
        # Remove autorizações da fixture para ensaiar novo registro.
        self.f.con.execute("DELETE FROM nivon_provas_externas")
        self.f.con.execute("DELETE FROM nivon_autorizacoes")
        self.f.con.commit()
        doc = self.f.documento
        editorial_texto = "Briefing NIVON sintético e revisado."
        edicao = {
            "estado": "EDICAO_OFFLINE_PREPARADA_SEM_ENVIO",
            "enviado": False, "texto": editorial_texto,
            "sha256": doc["sha256_editorial"],
            "preflight_editorial": {
                "apto_revisao": True, "bloqueios": [],
                "modo": "OFFLINE_SEM_ENVIO",
                "sha256_texto": doc["sha256_editorial"],
            }
        }
        from test_outbox_whatsapp import CHAVE_AUDITORIA
        with self.assertRaises(ErroProvaExterna):
            registrar_autorizacao(
                self.f.con, self.f.modelo, edicao_editorial=edicao,
                documento=doc, assinatura=self.f.assinatura,
                chave_auditoria=CHAVE_AUDITORIA,
            )
        self.assertEqual(self.f.con.execute(
            "SELECT count(*) FROM nivon_autorizacoes").fetchone()[0], 0)

    def test_base_legada_sem_digest_das_provas_nao_despacha(self):
        self.f.con.execute("DELETE FROM nivon_provas_externas")
        self.f.con.commit()
        self._nao_despacha()

    def test_comprovante_de_outra_edicao_mesmo_reassinado_nao_vale(self):
        self.f.comprovantes[0]["edicao"] = "2026-10-21"
        self._assinar(0)
        self._nao_despacha()

    def test_comprovante_sem_emissor_confiavel_nao_vale(self):
        emissor = self.f.comprovantes[0]["emissor_id"]
        del self.f.emissores[emissor]
        self._nao_despacha()

    def test_persistir_so_hash_sem_comprovantes_brutos(self):
        conteudo = self.f.path.read_bytes()
        self.assertNotIn(b"EMISSOR_REVISAO_EDITORIAL_SINTETICO", conteudo)
        self.assertNotIn(b"REVISAO_SINTETICA_001", conteudo)
        self.assertEqual(self.f.con.execute(
            "SELECT count(*) FROM nivon_provas_externas").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
