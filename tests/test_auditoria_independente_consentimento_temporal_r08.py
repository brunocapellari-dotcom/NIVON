"""Auditoria independente de ordem temporal do consentimento R08.

Apenas HMAC sintético e SQLite em memória. Nunca contém PII real,
chaves operacionais, rede, integração Meta ou qualquer envio.
"""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
import unittest

from nivon.outbox_briefing import abrir_outbox
from nivon.outbox_unificada import (
    ErroControleEnvio,
    mensagem_de_prova,
    registrar_decisao_consentimento,
    reservar_na_transacao,
    verificar_consentimento_pre_post,
)

_CHAVE_TESTE = b"CHAVE-FICTICIA-AUDITORIA-CONSENTIMENTO-R08-SEM-USO-REAL-123"
_DESTINATARIO = hmac.new(
    b"DESTINATARIO-FICTICIO-NAO-REVERSIVEL-R08-TEST-000000",
    b"TELEFONE_NAO_REAL_R08", hashlib.sha256,
).hexdigest()
_DIA = "2026-10-20"
_RESERVA = "2026-10-20T08:00:00-03:00"
_CONCESSAO_ANTERIOR = "2026-10-20T07:00:00-03:00"
_CONCESSAO_POSTERIOR = "2026-10-20T09:00:00-03:00"
_CONCESSAO_FUTURA = "2099-10-20T07:00:00-03:00"


def _registrar(db: sqlite3.Connection, *, acao: str, momento: str,
               evidencia: str) -> None:
    msg = mensagem_de_prova(
        acao=acao, destinatario_hmac=_DESTINATARIO,
        evidencia_id=evidencia, em=momento,
    )
    sig = hmac.new(_CHAVE_TESTE, msg, hashlib.sha256).hexdigest()
    registrar_decisao_consentimento(
        db, acao=acao, destinatario_hmac=_DESTINATARIO,
        evidencia_id=evidencia, em=momento, assinatura=sig,
        chave_verificacao=_CHAVE_TESTE,
    )


def _reservar(db: sqlite3.Connection, agora: str, intencao: str) -> None:
    db.execute("BEGIN IMMEDIATE")
    try:
        reservar_na_transacao(
            db, dia_local=_DIA, destinatario_hmac=_DESTINATARIO,
            canal="BRIEFING", intencao_id=intencao, agora=agora,
        )
        db.commit()
    except BaseException:
        db.rollback()
        raise


class TestAuditoriaConsentimentoTemporalR08(unittest.TestCase):
    def setUp(self):
        self.db = abrir_outbox(":memory:")

    def tearDown(self):
        self.db.close()

    def test_controle_concessao_anterior_reserva_e_verificacao_valida(self):
        _registrar(
            self.db, acao="CONCEDER",
            momento=_CONCESSAO_ANTERIOR,
            evidencia="CONCESSAO_VALIDADA_TESTE_001",
        )
        _reservar(self.db, _RESERVA, "controle-positivo")
        verificar_consentimento_pre_post(
            self.db, dia_local=_DIA, destinatario_hmac=_DESTINATARIO,
            canal="BRIEFING", intencao_id="controle-positivo",
        )
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_reservas_canonicas",
        ).fetchone()[0], 1)

    def test_controle_revogacao_anterior_impede_reserva(self):
        _registrar(
            self.db, acao="CONCEDER",
            momento=_CONCESSAO_ANTERIOR,
            evidencia="CONCESSAO_TESTE_REVO_001",
        )
        _registrar(
            self.db, acao="REVOGAR",
            momento="2026-10-20T07:30:00-03:00",
            evidencia="OPT_OUT_ASSINADO_TESTE_001",
        )
        with self.assertRaises(PermissionError):
            _reservar(self.db, _RESERVA, "controle-revogado")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_reservas_canonicas",
        ).fetchone()[0], 0)

    def test_p0_concessao_ano_2099_nao_autoriza_reserva_em_2026(self):
        # Implementações válidas podem rejeitar a concessão futura na
        # ingestão OU impedir uso antes do instante assinado.
        try:
            _registrar(
                self.db, acao="CONCEDER",
                momento=_CONCESSAO_FUTURA,
                evidencia="FUTURA_ASSINADA_TESTE_2099",
            )
        except (PermissionError, ErroControleEnvio):
            return
        with self.assertRaises(
            (PermissionError, ErroControleEnvio),
            msg="P0: assinatura válida com data futura não equivale a "
                "consentimento já vigente no momento da reserva",
        ):
            _reservar(self.db, _RESERVA, "futuro-2099")

    def test_p0_concessao_posterior_ao_corte_nao_autoriza_retroativamente(self):
        # O registro foi assinado às 09h; uma decisão às 08h não pode
        # usá-lo, mesmo que o evento seja conhecido na consulta atual.
        _registrar(
            self.db, acao="CONCEDER",
            momento=_CONCESSAO_POSTERIOR,
            evidencia="CONCESSAO_POSTERIOR_TESTE_001",
        )
        with self.assertRaises(
            (PermissionError, ErroControleEnvio),
            msg="P0: consentimento assinado após agora da reserva "
                "deve ser ignorado no corte (sem look-ahead)",
        ):
            _reservar(self.db, _RESERVA, "sem-lookahead")


if __name__ == "__main__":
    unittest.main()
