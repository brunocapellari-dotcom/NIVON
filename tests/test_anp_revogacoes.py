"""Revogação pós-ingestão e consultas ANP point-in-time — fixtures 100% falsas."""
import hmac
import json
import sqlite3
import unittest
from hashlib import sha256
from copy import deepcopy

from nivon.anp_revogacoes import ErroRevogacaoANP, registrar_revogacao_anp
from nivon.anp_semanal_store import (
    inicializar_store_anp, gravar_edicao_semanal, consultar_preco_semanal,
)
from test_anp_semanal_store import resumo, KEYS, indice_real, assinar_autorizacao


REVOKER = {
    "chave": b"fixture-revocation-authority-000000000000000001",
    "emissor": "independent-revocation-reviewer-fixture",
}
RECEIVED = "2026-10-20T18:00:00+00:00"
ISSUED = "2026-10-20T17:55:00+00:00"


def assinar_revogacao(*, sha="a"*64, dominio="DIREITOS_USO",
                      aprovacao_id=None, revogacao_id="rev-anp-20261020-001",
                      emitido=ISSUED, motivo="DIREITOS_INVALIDADOS"):
    body = {
        "versao":1, "revogacao_id":revogacao_id, "edicao_sha256":sha,
        "dominio_alvo":dominio,
        "aprovacao_id":aprovacao_id or f"test-{dominio}-{sha[:16]}",
        "emissor_id":REVOKER["emissor"],
        "motivo_codigo":motivo, "emitido_em":emitido,
    }
    encoded=json.dumps(body,sort_keys=True,ensure_ascii=True,
                       separators=(",",":"),allow_nan=False).encode()
    body["assinatura_hmac_sha256"]=hmac.new(
        REVOKER["chave"], b"NIVON_ANP_LPC_REVOGACAO_V1\x00"+encoded, sha256,
    ).hexdigest()
    return body


class TestRevogacaoANPLPC(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        inicializar_store_anp(self.db)
        self.addCleanup(self.db.close)
        self.r=resumo()
        self.entrada=self.r["sha256"]
        self.gravar(self.r)

    def gravar(self, r):
        return gravar_edicao_semanal(
            self.db, resumo=r, data_publicacao="2026-10-19T12:00:00+00:00",
            prova_publicacao_sha="b"*64, prova_direitos_sha="c"*64,
            classe="REAL_AUTORIZADO", direitos_confirmados=True,
            indice_evidencia=indice_real(r), habilitacao_real=True,
            aprovacoes_assinadas=assinar_autorizacao(
                r,"2026-10-19T12:00:00+00:00"),
            autoridades_confiaveis=KEYS, ids_revogados=frozenset(),
            verificado_em_confiavel="2026-10-20T15:30:00+00:00",
        )

    def consultar(self, as_of="2026-10-20T19:00:00+00:00"):
        return consultar_preco_semanal(
            self.db, municipio="SORRISO", produto="DIESEL S10", uf="MT",
            as_of=as_of,
        )

    def revogar(self, doc=None, received=RECEIVED, authority=None):
        return registrar_revogacao_anp(
            self.db,
            documento=doc if doc is not None else assinar_revogacao(),
            autoridade=authority if authority is not None else REVOKER,
            recebido_em_confiavel=received,
        )

    def test_revogacao_de_direitos_bloqueia_apenas_apos_conhecimento(self):
        self.assertEqual(self.consultar()["status"],"AMOSTRA_HISTORICA_PIT")
        v=self.revogar()
        self.assertTrue(v["registro_novo"])
        self.assertFalse(v["revogacao_distribuida"])
        self.assertEqual(self.consultar(
            "2026-10-20T17:59:59+00:00")["status"],"AMOSTRA_HISTORICA_PIT")
        bloqueado=self.consultar()
        self.assertEqual(bloqueado["status"],"EDICAO_REVOGADA")
        self.assertNotIn("preco_medio_revenda_brl_l",bloqueado)
        self.assertFalse(bloqueado["publicavel"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_revogacoes").fetchone()[0],1)

    def test_revogacao_de_layout_e_igualmente_bloqueante(self):
        r=self.revogar(assinar_revogacao(
            dominio="HOMOLOGACAO_LAYOUT", revogacao_id="rev-layout-001",
            motivo="ERRO_DE_LAYOUT"))
        self.assertEqual(r["dominio"],"HOMOLOGACAO_LAYOUT")
        self.assertEqual(self.consultar()["status"],"EDICAO_REVOGADA")

    def test_idempotencia_e_registro_inalteravel(self):
        doc=assinar_revogacao()
        self.assertTrue(self.revogar(doc)["registro_novo"])
        self.assertFalse(self.revogar(doc)["registro_novo"])
        outro=assinar_revogacao(
            revogacao_id=doc["revogacao_id"], motivo="EVIDENCIA_INVALIDA")
        with self.assertRaisesRegex(ErroRevogacaoANP,"conflitantes"):
            self.revogar(outro)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_revogacoes").fetchone()[0],1)

    def test_assinatura_modificada_nao_revoga(self):
        doc=assinar_revogacao()
        for field,value in [
            ("aprovacao_id","test-revoked-attestation"),
            ("edicao_sha256","f"*64),
            ("motivo_codigo","CHAVE_COMPROMETIDA"),
            ("emitido_em","2026-10-20T10:00:00+00:00"),
            ("emissor_id","another-revoker"),
        ]:
            m={**doc,field:value}
            with self.subTest(field=field), self.assertRaises(ErroRevogacaoANP):
                self.revogar(m)
        self.assertEqual(self.consultar()["status"],"AMOSTRA_HISTORICA_PIT")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_revogacoes").fetchone()[0],0)

    def test_autoridade_nao_pode_ser_revisor_original(self):
        doc=assinar_revogacao()
        forged={**REVOKER,"emissor":KEYS["DIREITOS_USO"]["emissor"]}
        doc["emissor_id"]=forged["emissor"]
        unsigned={k:v for k,v in doc.items() if k!="assinatura_hmac_sha256"}
        doc["assinatura_hmac_sha256"]=hmac.new(
            forged["chave"],b"NIVON_ANP_LPC_REVOGACAO_V1\x00"+
            json.dumps(unsigned,sort_keys=True,ensure_ascii=True,
                       separators=(",",":")).encode(),sha256).hexdigest()
        with self.assertRaisesRegex(ErroRevogacaoANP,"não pode ser revisor"):
            self.revogar(doc,authority=forged)
        self.assertEqual(self.consultar()["status"],"AMOSTRA_HISTORICA_PIT")

    def test_alvo_desconhecido_ou_aprovacao_errada_falham(self):
        for ed,ap in (("f"*64,None),("a"*64,"test-DIREITOS_USO-naoexiste")):
            doc=assinar_revogacao(
                sha=ed, aprovacao_id=ap, revogacao_id="rev-outro-001")
            with self.subTest(edicao=ed), self.assertRaisesRegex(
                    ErroRevogacaoANP,"ausente"):
                self.revogar(doc)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_revogacoes").fetchone()[0],0)

    def test_tempo_retroativo_e_tardio_bloqueados(self):
        with self.assertRaisesRegex(ErroRevogacaoANP,"tempo"):
            self.revogar(received="2026-10-20T17:00:00+00:00")
        with self.assertRaisesRegex(ErroRevogacaoANP,"tempo"):
            self.revogar(received="2026-10-24T18:00:00+00:00")
        old=assinar_revogacao(
            emitido="2026-10-20T14:58:00+00:00",
            revogacao_id="rev-antes-captura")
        with self.assertRaisesRegex(ErroRevogacaoANP,"antes da primeira captura"):
            self.revogar(old, received="2026-10-20T15:00:00+00:00")
        self.assertEqual(self.consultar()["status"],"AMOSTRA_HISTORICA_PIT")

    def test_revogacao_de_uma_revisao_nao_faz_fallback_silencioso(self):
        corrigido=resumo(sha="d"*64,preco=5.92,
                         coleta="2026-10-20T16:00:00+00:00")
        self.gravar(corrigido)
        self.assertEqual(self.consultar()["status"],"REVISOES_CONFLITANTES")
        self.revogar()
        bloqueio=self.consultar()
        self.assertEqual(bloqueio["status"],"EDICAO_REVOGADA")
        self.assertNotIn("preco_medio_revenda_brl_l",bloqueio)

    def test_sistema_sem_evento_de_revogacao_nao_comprova_frescor(self):
        # Esta consulta é historicamente válida para um DB local, mas não
        # prova que o feed remoto de revogações está sincronizado.
        self.assertEqual(self.consultar()["status"],"AMOSTRA_HISTORICA_PIT")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_revogacoes").fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
