"""Fluxo de auditoria E2E com artefatos e assinador 100% sintéticos."""
import json
from hashlib import sha256
import sqlite3
import unittest

from nivon.auditoria_e2e_mercados import (
    ErroAuditoriaMercado, auditar_previsao_ponta_a_ponta,
)
from nivon.ancora_previsoes_mercado import ErroAncoraMercado
from nivon.ledger_previsoes_mercado import anexar_previsao, inicializar_ledger
from nivon.proveniencia_previsoes_mercado import GENESIS, ErroRegistroPrevisao
from nivon.evidencia_bruta_mercados import ErroEvidenciaMercado
from test_proveniencia_previsoes_mercado import previsao, cotacao, calendario
from test_ancora_previsoes_mercado import (
    CHAVE_ASSINADOR_SINTETICO, LEDGER, criar_recibo_fake,
)


def artefatos(dia, valor, digest, captured):
    quote = cotacao(dia, valor, digest)
    raw = ("RAW TESTE " + dia).encode()
    norm = (json.dumps(quote, sort_keys=True, ensure_ascii=True) + "\n").encode()
    return {
        "arquivo_original": raw,
        "snapshot_jsonl": norm,
        "manifesto": {
            "schema": "NIVON_MARKET_RAW_NORM_V1",
            "fonte_id": "FONTE_SINTETICA",
            "fonte_url": "https://example.org/quotes",
            "raw_sha256": sha256(raw).hexdigest(),
            "normalizado_sha256": sha256(norm).hexdigest(),
            "capturado_em": captured,
            "parser_id": "PARSER-TESTE", "parser_versao": "0.1",
            "direitos_status": "NAO_HOMOLOGADO",
        },
    }


class TestAuditoriaE2EMercados(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        inicializar_ledger(self.con)
        self.head = anexar_previsao(
            self.con, previsao(), cabeca_atual_esperada_sha256=GENESIS)
        self.receipt = criar_recibo_fake(self.head["registro_sha256"])
        self.base = artefatos(
            "2026-10-13", "1000", "a"*64, "2026-10-14T10:00:00Z")
        self.alvo = artefatos(
            "2026-10-15", "1020", "c"*64, "2026-10-16T10:00:00Z")

    def tearDown(self):
        self.con.close()

    def executar(self, *, base=None, alvo=None, receipt=None, identity="TESTE-001"):
        return auditar_previsao_ponta_a_ponta(
            self.con, previsao_id=identity,
            recibo_ancora=receipt if receipt is not None else self.receipt,
            ledger_id=LEDGER, segredo_verificacao=CHAVE_ASSINADOR_SINTETICO,
            pacote_base=base if base is not None else self.base,
            pacote_alvo=alvo if alvo is not None else self.alvo,
            calendario_sessoes=calendario(),
            as_of="2026-10-16T12:00:00Z",
        )

    def test_e2e_cadeia_snapshots_e_backtest(self):
        res = self.executar()
        self.assertEqual(res["status"], "E2E_INTERNO_CONFERIDO_OFFLINE_NAO_HOMOLOGADO")
        self.assertEqual(res["item_backtest"]["classe_realizada"], "ALTA")
        self.assertEqual(res["item_backtest"]["valor_base"], "1000")
        self.assertEqual(res["item_backtest"]["valor_alvo"], "1020")
        self.assertTrue(res["recibo_mac_conferido"])
        self.assertFalse(res["publicavel"])
        self.assertFalse(res["parser_independente_verificado"])
        self.assertFalse(res["origem_mercado_autenticada"])
        self.assertFalse(res["anchorage_worm_comprovada"])
        self.assertIsNone(res["probabilidades_calibradas"])

    def test_raw_base_adulterado_bloqueia(self):
        base = dict(self.base, arquivo_original=b"modificado")
        with self.assertRaisesRegex(ErroEvidenciaMercado, "original diverge"):
            self.executar(base=base)

    def test_snapshot_alvo_adulterado_bloqueia(self):
        alvo = dict(self.alvo, snapshot_jsonl=b"{}\n")
        with self.assertRaisesRegex(ErroEvidenciaMercado, "normalizado diverge"):
            self.executar(alvo=alvo)

    def test_base_capturada_depois_da_emissao_bloqueia(self):
        base = dict(self.base, manifesto={
            **self.base["manifesto"],
            "capturado_em": "2026-10-14T13:00:00Z",
        })
        with self.assertRaisesRegex(ErroEvidenciaMercado, "após as_of"):
            self.executar(base=base)

    def test_alvo_capturado_depois_do_corte_bloqueia(self):
        alvo = dict(self.alvo, manifesto={
            **self.alvo["manifesto"],
            "capturado_em": "2026-10-16T13:00:00Z",
        })
        with self.assertRaisesRegex(ErroEvidenciaMercado, "após as_of"):
            self.executar(alvo=alvo)

    def test_recalculo_detecta_preco_base_revisado_na_origem(self):
        base = artefatos("2026-10-13", "1100", "b"*64,
                         "2026-10-14T10:00:00Z")
        with self.assertRaisesRegex(ErroRegistroPrevisao, "preço-base"):
            self.executar(base=base)

    def test_recibo_adulterado_bloqueia_antes_do_preco(self):
        rec = dict(self.receipt, cabeca_sha256="f"*64)
        with self.assertRaises(ErroAncoraMercado):
            self.executar(receipt=rec)

    def test_previsao_id_nao_existe_no_ledger(self):
        with self.assertRaisesRegex(ErroAuditoriaMercado, "não encontrada"):
            self.executar(identity="FALSA-001")

    def test_pacote_incompleto_rejeitado(self):
        with self.assertRaisesRegex(ErroAuditoriaMercado, "pacote"):
            self.executar(base={"arquivo_original": b"teste"})


if __name__ == "__main__":
    unittest.main()
