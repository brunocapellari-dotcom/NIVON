import copy
import os
import sqlite3
import tempfile
import unittest

from nivon.ledger_previsoes_mercado import (
    ErroLedgerPrevisao, anexar_previsao, consultar_ledger, inicializar_ledger,
)
from nivon.proveniencia_previsoes_mercado import GENESIS


def forecast(i=1):
    return {
        "previsao_id": "SINTETICO-" + str(i),
        "serie_id": "CME:SOJA:2026-11:AJUSTE",
        "modelo_versao": "v1",
        "identidade_economica": [
            "CME", "SOJA", "2026-11", "AJUSTE", "USC/BU",
            None, "ZS", None, None, None, None, None,
        ],
        "emitido_em": "2026-10-14T12:00:00Z",
        "registrado_em": "2026-10-14T12:0%d:00Z" % i,
        "treinado_ate": "2026-10-13T10:00:00Z",
        "sessao_base": "2026-10-13",
        "sessao_alvo": "2026-10-15",
        "horizonte_sessoes": 2,
        "preco_base": "1000",
        "base_edicao_sha256": "a" * 64,
        "regra_rotulagem": "RETORNO_BANDA",
        "banda_relativa": "0.01",
        "probabilidades": {
            "ALTA": "0.7", "BAIXA": "0.1", "ESTABILIDADE": "0.2"
        },
        "evidencia_registro_id": "TESTE-" + str(i),
        "evidencia_registro_sha256": "b" * 64,
    }


class TestLedgerPrevisoes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "previsoes.sqlite")
        self.con = sqlite3.connect(self.db, timeout=2)
        inicializar_ledger(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_append_e_reabrir(self):
        a = anexar_previsao(self.con, forecast(1),
                             cabeca_atual_esperada_sha256=GENESIS)
        self.con.close()
        self.con = sqlite3.connect(self.db, timeout=2)
        b = anexar_previsao(self.con, forecast(2),
                             cabeca_atual_esperada_sha256=a["registro_sha256"])
        prova = consultar_ledger(self.con,
                    cabeca_esperada_sha256=b["registro_sha256"])
        self.assertEqual(prova["quantidade"], 2)
        self.assertEqual(prova["registros"][0]["previsao"]["previsao_id"],
                         "SINTETICO-1")
        self.assertFalse(prova["ancora_externa_autenticada"])
        self.assertFalse(prova["publicavel"])

    def test_update_delete_bloqueados_no_sqlite(self):
        a = anexar_previsao(self.con, forecast(1),
                             cabeca_atual_esperada_sha256=GENESIS)
        for sql in (
            "UPDATE nivon_previsoes_ledger SET previsao_id='ALTERADO'",
            "DELETE FROM nivon_previsoes_ledger",
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.con.execute(sql)
        self.con.rollback()
        self.assertEqual(
            consultar_ledger(self.con, cabeca_esperada_sha256=a["registro_sha256"])["quantidade"], 1)

    def test_dados_duplicados_bloqueados_sem_append(self):
        a = anexar_previsao(self.con, forecast(1),
                             cabeca_atual_esperada_sha256=GENESIS)
        with self.assertRaises(ErroLedgerPrevisao):
            anexar_previsao(self.con, forecast(1),
                             cabeca_atual_esperada_sha256=a["registro_sha256"])
        self.assertEqual(
            consultar_ledger(self.con, cabeca_esperada_sha256=a["registro_sha256"])["quantidade"], 1)

    def test_ancora_antiga_bloqueia_novo_append(self):
        a = anexar_previsao(self.con, forecast(1),
                             cabeca_atual_esperada_sha256=GENESIS)
        with self.assertRaises(ErroLedgerPrevisao):
            anexar_previsao(self.con, forecast(2),
                             cabeca_atual_esperada_sha256=GENESIS)
        self.assertEqual(
            consultar_ledger(self.con, cabeca_esperada_sha256=a["registro_sha256"])["quantidade"], 1)

    def test_rollback_de_evento_invalido(self):
        with self.assertRaises(ErroLedgerPrevisao):
            anexar_previsao(self.con, dict(forecast(1), preco_base="NaN"),
                             cabeca_atual_esperada_sha256=GENESIS)
        self.assertEqual(
            consultar_ledger(self.con, cabeca_esperada_sha256=GENESIS)["status"], "LEDGER_VAZIO")
        anexar_previsao(self.con, forecast(1),
                         cabeca_atual_esperada_sha256=GENESIS)

    def test_registro_retroativo_nao_reordena_cadeia(self):
        a = anexar_previsao(self.con, forecast(2),
                             cabeca_atual_esperada_sha256=GENESIS)
        with self.assertRaisesRegex(ErroLedgerPrevisao, "retroativo"):
            anexar_previsao(self.con, forecast(1),
                             cabeca_atual_esperada_sha256=a["registro_sha256"])

    def test_arquivo_editado_externamente_detectado_pela_ancora(self):
        a = anexar_previsao(self.con, forecast(1),
                             cabeca_atual_esperada_sha256=GENESIS)
        # Um adversário com acesso ao DB pode dropar trigger. É por isso
        # que a cabeça precisa estar fora do banco.
        self.con.execute("DROP TRIGGER nivon_previsoes_sem_update")
        self.con.execute(
            "UPDATE nivon_previsoes_ledger SET registro_sha256=?",
            ("f"*64,))
        self.con.commit()
        with self.assertRaises(ErroLedgerPrevisao):
            consultar_ledger(self.con, cabeca_esperada_sha256=a["registro_sha256"])

    def test_conexao_ja_em_transacao_recusada(self):
        self.con.execute("BEGIN")
        try:
            with self.assertRaisesRegex(ErroLedgerPrevisao, "transação pendente"):
                anexar_previsao(self.con, forecast(1),
                                 cabeca_atual_esperada_sha256=GENESIS)
        finally:
            self.con.rollback()

    def test_concorrencia_mesma_ancora_nao_escreve_duas_vezes(self):
        con2 = sqlite3.connect(self.db, timeout=2)
        try:
            r1 = anexar_previsao(self.con, forecast(1),
                                cabeca_atual_esperada_sha256=GENESIS)
            with self.assertRaises(ErroLedgerPrevisao):
                anexar_previsao(con2, forecast(2),
                               cabeca_atual_esperada_sha256=GENESIS)
            prova = consultar_ledger(con2,
                        cabeca_esperada_sha256=r1["registro_sha256"])
            self.assertEqual(prova["quantidade"], 1)
        finally:
            con2.close()


if __name__ == "__main__":
    unittest.main()
