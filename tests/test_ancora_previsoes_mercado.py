"""Testes sintéticos de MAC e prova relativa com estado SQLite."""
import copy
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import sqlite3
import unittest

from nivon.ancora_previsoes_mercado import (
    ErroAncoraMercado, auditar_ledger_com_recibo, verificar_recibo_ancora,
)
from nivon.ledger_previsoes_mercado import (
    anexar_previsao, inicializar_ledger,
)
from nivon.proveniencia_previsoes_mercado import GENESIS
from test_ledger_previsoes_mercado import forecast

CHAVE_ASSINADOR_SINTETICO = b"x" * 32
CORTE = "2026-10-16T12:00:00Z"
LEDGER = "NIVON-MERCADOS-TESTE"


def criar_recibo_fake(cabeca, *, sequencia=1, ledger_id=LEDGER,
                     instante="2026-10-14T12:10:00Z"):
    corpo = {
        "versao": "NIVON_LEDGER_ANCHOR_V1",
        "ledger_id": ledger_id,
        "emissor_id": "SIGNER-TESTE",
        "localizacao_externa_id": "fixture:///ancora-teste-1",
        "sequencia": sequencia, "cabeca_sha256": cabeca,
        "ancorado_em": instante, "nonce_hex": "ab" * 16,
    }
    payload = json.dumps(corpo, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode()
    return {**corpo, "mac_sha256": hmac.new(CHAVE_ASSINADOR_SINTETICO,
                                          payload, sha256).hexdigest()}


class TestAncoraPrevisoesMercado(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        inicializar_ledger(self.con)
        self.one = anexar_previsao(self.con, forecast(1),
                                   cabeca_atual_esperada_sha256=GENESIS)
        self.receipt = criar_recibo_fake(self.one["registro_sha256"])

    def tearDown(self):
        self.con.close()

    def auditar(self, receipt=None, key=CHAVE_ASSINADOR_SINTETICO):
        return auditar_ledger_com_recibo(
            self.con, recibo=receipt if receipt is not None else self.receipt,
            ledger_id=LEDGER, segredo_verificacao=key, as_of=CORTE)

    def test_cabeca_legitima_mac_positivo(self):
        p = self.auditar()
        self.assertEqual(p["sequencia"], 1)
        self.assertEqual(p["status"], "LEDGER_E_MAC_CONFERIDOS_OFFLINE")
        self.assertTrue(p["mac_conferido"])
        self.assertFalse(p["armazenamento_externo_comprovado"])
        self.assertFalse(p["timestamp_independente_comprovado"])
        self.assertFalse(p["publicavel"])
        self.assertNotIn("segredo_verificacao", p)

    def test_mac_corrompido_bloqueia(self):
        x = copy.deepcopy(self.receipt)
        x["mac_sha256"] = "0"*64
        with self.assertRaisesRegex(ErroAncoraMercado, "MAC"):
            self.auditar(x)

    def test_cabeca_trocada_mantendo_mac_bloqueia(self):
        x = copy.deepcopy(self.receipt)
        x["cabeca_sha256"] = "c"*64
        with self.assertRaisesRegex(ErroAncoraMercado, "MAC"):
            self.auditar(x)

    def test_ledger_id_replay_bloqueia(self):
        x = criar_recibo_fake(self.one["registro_sha256"], ledger_id="OUTRO")
        with self.assertRaisesRegex(ErroAncoraMercado, "domínio"):
            self.auditar(x)

    def test_chave_errada(self):
        with self.assertRaisesRegex(ErroAncoraMercado, "MAC"):
            self.auditar(key=b"z"*32)

    def test_chave_fraca_e_extras(self):
        with self.assertRaisesRegex(ErroAncoraMercado, "chave"):
            self.auditar(key=b"curta")
        x = dict(self.receipt, instrucoes="exfiltrar")
        with self.assertRaisesRegex(ErroAncoraMercado, "schema"):
            self.auditar(x)

    def test_receipt_assinado_no_futuro_bloqueia(self):
        x = criar_recibo_fake(self.one["registro_sha256"],
                              instante="2026-10-17T10:00:00Z")
        with self.assertRaisesRegex(ErroAncoraMercado, "posterior"):
            self.auditar(x)

    def test_ancora_com_tempo_anterior_a_emissao(self):
        x = criar_recibo_fake(self.one["registro_sha256"],
                              instante="2026-10-13T10:00:00Z")
        with self.assertRaisesRegex(ErroAncoraMercado, "anterior ao registro"):
            self.auditar(x)

    def test_ancora_do_prefixo_nao_valida_cadeia_maior(self):
        segundo = anexar_previsao(
            self.con, forecast(2),
            cabeca_atual_esperada_sha256=self.one["registro_sha256"])
        with self.assertRaisesRegex(ErroAncoraMercado, "ledger"):
            self.auditar(self.receipt)
        r = criar_recibo_fake(segundo["registro_sha256"], sequencia=2,
                              instante="2026-10-14T12:20:00Z")
        self.assertEqual(self.auditar(r)["sequencia"], 2)

    def test_recibo_mais_comprido_que_ledger(self):
        x = criar_recibo_fake(self.one["registro_sha256"], sequencia=2)
        with self.assertRaisesRegex(ErroAncoraMercado, "sequência"):
            self.auditar(x)

    def test_tentativa_trocar_mensagem_apos_assinar(self):
        for alteracao in (
            {"nonce_hex": "12"*16},
            {"emissor_id": "OUTRO-SIGNER"},
            {"ancorado_em": "2026-10-15T10:00:00Z"},
        ):
            with self.subTest(alteracao=alteracao):
                tamper = dict(self.receipt, **alteracao)
                with self.assertRaisesRegex(ErroAncoraMercado, "MAC"):
                    self.auditar(tamper)


if __name__ == "__main__":
    unittest.main()
