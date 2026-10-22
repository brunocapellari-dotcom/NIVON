"""Checkpoint ANP de revogações: só fixtures e chaves falsas, sem rede."""
import hmac
import json
import sqlite3
import unittest
from hashlib import sha256

from nivon.anp_revogacoes_frescor import (
    ErroCheckpointANP, estado_revogacoes_local,
    receber_checkpoint_revogacoes, verificar_frescor_revogacoes,
)
from nivon.anp_semanal_store import (
    inicializar_store_anp, gravar_edicao_semanal, consultar_preco_semanal,
)
from nivon.anp_revogacoes import registrar_revogacao_anp
from test_anp_semanal_store import (
    KEYS, resumo, indice_real, assinar_autorizacao,
)
from test_anp_revogacoes import REVOKER, assinar_revogacao

FEED = {
    "chave": b"fixture-separate-feed-authority-0000000000000001",
    "emissor": "anp-revocation-feed-fixture",
}
PREFIX = b"NIVON_ANP_LPC_REVOGACOES_CHECKPOINT_V1\x00"


def fixture_checkpoint(db, *, seq=1,
                       coverage="2026-10-20T16:15:00+00:00",
                       issued="2026-10-20T16:16:00+00:00",
                       received="2026-10-20T16:20:00+00:00",
                       valid="2026-10-20T20:16:00+00:00"):
    estado = estado_revogacoes_local(db, ate=coverage)
    body = {
        "versao": 1, "escopo": "ANP_LPC_REVOGACOES",
        "emissor_id": FEED["emissor"],
        "sequencia": seq, "cobertura_ate": coverage,
        "emitido_em": issued, "valido_ate": valid,
        **estado,
    }
    return assinar_checkpoint(body), received


def assinar_checkpoint(campos, authority=FEED):
    body = {k: v for k, v in campos.items() if k != "assinatura_hmac_sha256"}
    payload = json.dumps(body, sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"), allow_nan=False).encode()
    return {
        **body,
        "assinatura_hmac_sha256": hmac.new(
            authority["chave"], PREFIX + payload, sha256,
        ).hexdigest(),
    }


class TestFrescorRevogacoes(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        inicializar_store_anp(self.db)
        entrada = resumo()
        gravar_edicao_semanal(
            self.db, resumo=entrada,
            data_publicacao="2026-10-19T12:00:00+00:00",
            prova_publicacao_sha="b"*64, prova_direitos_sha="c"*64,
            classe="REAL_AUTORIZADO", direitos_confirmados=True,
            indice_evidencia=indice_real(entrada), habilitacao_real=True,
            aprovacoes_assinadas=assinar_autorizacao(
                entrada,"2026-10-19T12:00:00+00:00"),
            autoridades_confiaveis=KEYS, ids_revogados=frozenset(),
            verificado_em_confiavel="2026-10-20T15:30:00+00:00",
        )

    def query(self, as_of="2026-10-20T18:00:00+00:00"):
        return consultar_preco_semanal(
            self.db, uf="MT", municipio="SORRISO", produto="DIESEL S10",
            as_of=as_of,
        )

    def add_checkpoint(self, checkpoint=None, received=None):
        doc, time = fixture_checkpoint(self.db)
        return receber_checkpoint_revogacoes(
            self.db,
            checkpoint=doc if checkpoint is None else checkpoint,
            autoridade=FEED, recebido_em_confiavel=received or time,
        )

    def add_revocation(self, received="2026-10-20T18:00:00+00:00"):
        return registrar_revogacao_anp(
            self.db, documento=assinar_revogacao(),
            autoridade=REVOKER, recebido_em_confiavel=received,
        )

    def test_sem_checkpoint_nao_expoe_preco(self):
        r = self.query()
        self.assertEqual(r["status"], "REVOGACOES_SEM_CHECKPOINT")
        self.assertNotIn("preco_medio_revenda_brl_l", r)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_checkpoints"
        ).fetchone()[0], 0)

    def test_checkpoint_assinado_valido_expoe_apenas_historico_nao_publicavel(self):
        receipt = self.add_checkpoint()
        self.assertTrue(receipt["registro_novo"])
        self.assertFalse(receipt["fonte_real_sincronizada"])
        price = self.query()
        self.assertEqual(price["status"], "AMOSTRA_HISTORICA_PIT")
        self.assertEqual(price["preco_medio_revenda_brl_l"], "5.85")
        self.assertFalse(price["publicavel"])
        self.assertEqual(price["checkpoint_revogacoes_sequencia"], 1)
        self.assertEqual(price["checkpoint_revogacoes_cobertura_ate"],
                         "2026-10-20T16:15:00+00:00")

    def test_sem_vazamento_futuro_em_consulta_historica(self):
        self.add_checkpoint()
        # Edição já coletada, mas não havia checkpoint recebido neste instante.
        response = self.query("2026-10-20T16:19:59+00:00")
        self.assertEqual(response["status"], "REVOGACOES_SEM_CHECKPOINT")
        self.assertNotIn("preco_medio_revenda_brl_l", response)
        self.assertEqual(self.query("2026-10-20T16:21:00+00:00")["status"],
                         "AMOSTRA_HISTORICA_PIT")

    def test_validade_do_checkpoint_nao_e_indefinida(self):
        self.add_checkpoint()
        r = self.query("2026-10-20T18:16:00+00:00")
        self.assertEqual(r["status"], "REVOGACOES_CHECKPOINT_VENCIDO")
        self.assertNotIn("preco_medio_revenda_brl_l", r)
        self.assertEqual(verificar_frescor_revogacoes(
            self.db, as_of="2026-10-20T21:00:00+00:00")["status"],
            "REVOGACOES_CHECKPOINT_VENCIDO")

    def test_checkpoint_adulterado_ou_emissor_incorreto_falha(self):
        doc, _ = fixture_checkpoint(self.db)
        for k, v in [
            ("hash_revogacoes", "a"*64), ("total_revogacoes", 2),
            ("sequencia", 7), ("escopo", "OUTRO"),
            ("emissor_id", "issuer-malicioso"),
        ]:
            with self.subTest(k=k), self.assertRaises(ErroCheckpointANP):
                self.add_checkpoint({**doc, k: v})
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_checkpoints").fetchone()[0], 0)

    def test_checkpoint_assinado_mas_lista_incorreta_bloqueia(self):
        doc, _ = fixture_checkpoint(self.db)
        falha = assinar_checkpoint({**doc, "total_revogacoes": 1})
        with self.assertRaisesRegex(ErroCheckpointANP, "diverge"):
            self.add_checkpoint(falha)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_checkpoints").fetchone()[0], 0)

    def test_replay_idempotente_e_rollback_de_sequencia(self):
        original, recebido = fixture_checkpoint(self.db)
        self.assertTrue(self.add_checkpoint(original, recebido)["registro_novo"])
        self.assertFalse(self.add_checkpoint(original, recebido)["registro_novo"])
        mesmo_seq = assinar_checkpoint({**original, "emitido_em":
                                           "2026-10-20T16:17:00+00:00"})
        with self.assertRaisesRegex(ErroCheckpointANP, "mesma sequência"):
            self.add_checkpoint(mesmo_seq)
        novo, recebido2 = fixture_checkpoint(
            self.db, seq=3, coverage="2026-10-20T17:00:00+00:00",
            issued="2026-10-20T17:01:00+00:00",
            received="2026-10-20T17:05:00+00:00",
            valid="2026-10-20T21:01:00+00:00",
        )
        self.assertTrue(self.add_checkpoint(novo, recebido2)["registro_novo"])
        antiga, hora = fixture_checkpoint(
            self.db, seq=2, coverage="2026-10-20T16:30:00+00:00",
            issued="2026-10-20T16:31:00+00:00",
            received="2026-10-20T16:35:00+00:00",
            valid="2026-10-20T20:31:00+00:00",
        )
        with self.assertRaisesRegex(ErroCheckpointANP, "rollback"):
            self.add_checkpoint(antiga, hora)

    def test_atestacao_expirada_futura_ou_sem_fuso_bloqueia(self):
        original, received = fixture_checkpoint(self.db)
        for key, value in [
            ("emitido_em", "2026-10-20T19:00:00+00:00"),
            ("valido_ate", "2026-10-20T16:17:00+00:00"),
            ("cobertura_ate", "2026-10-20T12:00:00+00:00"),
            ("emitido_em", "2026-10-20T16:16:00"),
        ]:
            with self.subTest(key=key), self.assertRaises(ErroCheckpointANP):
                self.add_checkpoint(assinar_checkpoint({**original, key: value}), received)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_checkpoints").fetchone()[0], 0)

    def test_revogacao_local_sem_proximo_checkpoint_falha_fechada(self):
        self.add_checkpoint()
        self.add_revocation()
        r = verificar_frescor_revogacoes(
            self.db, as_of="2026-10-20T18:05:00+00:00")
        self.assertEqual(r["status"], "REVOGACOES_NAO_SINCRONIZADAS")
        self.assertEqual(self.query("2026-10-20T18:05:00+00:00")["status"],
                         "EDICAO_REVOGADA")
        novo, receipt = fixture_checkpoint(
            self.db, seq=2, coverage="2026-10-20T18:02:00+00:00",
            issued="2026-10-20T18:03:00+00:00",
            received="2026-10-20T18:04:00+00:00",
            valid="2026-10-20T22:03:00+00:00",
        )
        self.add_checkpoint(novo, receipt)
        self.assertEqual(verificar_frescor_revogacoes(
            self.db, as_of="2026-10-20T18:05:00+00:00")["status"],
            "CHECKPOINT_FRESCO_APENAS_LOCAL")

    def test_insercao_retroativa_apos_checkpoint_e_detectada(self):
        doc, received = fixture_checkpoint(
            self.db, seq=1, coverage="2026-10-20T18:05:00+00:00",
            issued="2026-10-20T18:06:00+00:00",
            received="2026-10-20T18:07:00+00:00",
            valid="2026-10-20T22:06:00+00:00",
        )
        self.add_checkpoint(doc, received)
        self.add_revocation("2026-10-20T18:00:00+00:00")
        response = verificar_frescor_revogacoes(
            self.db, as_of="2026-10-20T18:10:00+00:00")
        self.assertEqual(response["status"], "REVOGACOES_LISTA_DIVERGENTE")

    def test_tolerancia_invalida_bloqueia(self):
        for value in (0, -1, True, 400):
            with self.subTest(value=value), self.assertRaises(ErroCheckpointANP):
                verificar_frescor_revogacoes(
                    self.db, as_of="2026-10-20T18:00:00+00:00",
                    tolerancia_minutos=value,
                )


if __name__ == "__main__":
    unittest.main()
