"""Auditoria E2E forte do formato CSV NIVON, sem feed externo."""
from hashlib import sha256
import json
import sqlite3
import unittest

from nivon.auditoria_e2e_mercados import auditar_previsao_ponta_a_ponta_csv_canonico
from nivon.auditoria_extracao_csv_mercados import ErroExtracaoCSV
from nivon.ledger_previsoes_mercado import inicializar_ledger, anexar_previsao
from nivon.proveniencia_previsoes_mercado import GENESIS
from test_ancora_previsoes_mercado import (
    LEDGER, CHAVE_ASSINADOR_SINTETICO, criar_recibo_fake,
)
from test_proveniencia_previsoes_mercado import previsao, calendario
from test_auditoria_extracao_csv_mercados import (
    kit, row, rehash, to_jsonl,
)


def pacote(d, price, edicao, captured):
    registro = row(d=d, price=price)
    registro["edicao_sha256"] = edicao
    raw, norm, manifest = kit([registro])
    return {
        "arquivo_original": raw, "snapshot_jsonl": norm,
        "manifesto": {**manifest, "capturado_em": captured},
    }


class TestE2ECSVCanonico(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        inicializar_ledger(self.con)
        evento = anexar_previsao(
            self.con, previsao(), cabeca_atual_esperada_sha256=GENESIS)
        self.receipt = criar_recibo_fake(evento["registro_sha256"])
        self.base = pacote("2026-10-13", "1000", "a"*64,
                           "2026-10-14T10:00:00Z")
        self.alvo = pacote("2026-10-15", "1020", "c"*64,
                           "2026-10-16T10:00:00Z")

    def tearDown(self):
        self.con.close()

    def auditar(self, base=None, alvo=None):
        return auditar_previsao_ponta_a_ponta_csv_canonico(
            self.con, previsao_id="TESTE-001",
            recibo_ancora=self.receipt,
            ledger_id=LEDGER,
            segredo_verificacao=CHAVE_ASSINADOR_SINTETICO,
            pacote_base=self.base if base is None else base,
            pacote_alvo=self.alvo if alvo is None else alvo,
            calendario_sessoes=calendario(),
            as_of="2026-10-16T12:00:00Z",
        )

    def test_previsao_com_csv_base_alvo_verificados(self):
        r = self.auditar()
        self.assertTrue(r["extracao_csv_canonico_conferida"])
        self.assertEqual(r["linhas_base_conferidas"], 1)
        self.assertEqual(r["linhas_alvo_conferidas"], 1)
        self.assertEqual(r["item_backtest"]["classe_realizada"], "ALTA")
        self.assertFalse(r["parser_oficial_mercado_validado"])
        self.assertFalse(r["licenca_publicacao_verificada"])
        self.assertFalse(r["publicavel"])

    def test_preco_alvo_foi_reformatado_e_hash_manifesto_refeito(self):
        p = self.alvo
        obj = json.loads(p["snapshot_jsonl"])
        obj["preco"] = "1020.0"
        novo_jsonl = to_jsonl([obj])
        alterado = {
            **p, "snapshot_jsonl": novo_jsonl,
            "manifesto": rehash(p["arquivo_original"],
                                novo_jsonl, p["manifesto"]),
        }
        # O preço econômico Decimal não se altera; apenas a checagem
        # literal da linha CSV pode detectar essa mudança.
        with self.assertRaisesRegex(ErroExtracaoCSV, "divergência"):
            self.auditar(alvo=alterado)

    def test_raw_alvo_tem_linha_extra_omitida_no_jsonl(self):
        p = self.alvo
        extra = row(d="2026-10-14", price="1010")
        extra["edicao_sha256"] = "c"*64
        atual = row(d="2026-10-15", price="1020")
        atual["edicao_sha256"] = "c"*64
        raw, _, _ = kit([extra, atual])
        alterado = {
            **p, "arquivo_original": raw,
            "manifesto": rehash(raw, p["snapshot_jsonl"], p["manifesto"]),
        }
        with self.assertRaisesRegex(ErroExtracaoCSV, "omissão"):
            self.auditar(alvo=alterado)

    def test_manifesto_de_parser_generico_nao_homologa_csv(self):
        m = dict(self.alvo["manifesto"], parser_id="PARSER-DESCONHECIDO")
        alterado = {**self.alvo, "manifesto": m}
        with self.assertRaisesRegex(ErroExtracaoCSV, "parser"):
            self.auditar(alvo=alterado)


if __name__ == "__main__":
    unittest.main()
