"""Testes E2E offline: agrobr fictício -> normalização -> ledger -> staging.

Fixtures são sintéticas e NÃO se apresentam como coleta MDIC/CFTC real.
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from nivon.agrobr_mercados import (
    CONTRATOS, ErroAgrobrMercados, coletar_mercado_agrobr,
)
from nivon.ingestao_fontes_reais import exportar_jsonl

HOJE = date(2026, 10, 26)
AGORA = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)


class Quadro:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient="records"):
        assert orient == "records"
        return [dict(r) for r in self.rows]


class Meta:
    def __init__(self, source, license="livre", contract="1.1", version="2.0.0",
                 warnings=None):
        self.source = source
        self.license = license
        self.contract = contract
        self.version = version
        self.warnings = warnings or []

    def to_dict(self):
        return {
            "selected_source": self.source,
            "license": self.license,
            "contract_version": self.contract,
            "agrobr_version": self.version,
            "source_url": "https://comexstat.mdic.gov.br",
            "raw_content_hash": "a" * 64,
            "validation_passed": True,
            "validation_warnings": self.warnings,
        }


class FakeProvider:
    def __init__(self, rows, meta):
        self.rows, self.meta = rows, meta
        self.calls = []

    async def __call__(self, dataset, produto, **kwargs):
        self.calls.append((dataset, produto, kwargs))
        return Quadro(self.rows), self.meta


def linha_comex(*, kg=1000.0, fob=500.0, uf="MT", produto="soja", ano=2026, mes=9,
                frete=None, seguro=None):
    return {
        "ano": ano, "mes": mes, "produto": produto, "uf": uf,
        "kg_liquido": kg, "valor_fob_usd": fob, "volume_ton": kg / 1000,
        "valor_frete_usd": frete, "valor_seguro_usd": seguro,
    }


def linha_cftc(*, fundos_compra=100, fundos_venda=150, data="2026-10-20"):
    return {
        "data": data, "produto": "soja", "contrato": "SOYBEANS",
        "codigo_cftc": "005602", "posicoes_abertas": 15000,
        "fundos_compra": fundos_compra, "fundos_venda": fundos_venda,
        "fundos_spread": 20, "fundos_saldo": fundos_compra - fundos_venda,
    }


class MercadosAgrobrTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.args = {"banco": self.root / "fontes.sqlite",
                     "raw_dir": self.root / "raw",
                     "executar": True, "instante": AGORA, "hoje": HOJE}

    def test_comex_exportacao_revisoes_idempotentes_e_stage(self):
        provider = FakeProvider([linha_comex()], Meta("comexstat"))
        opts = dict(self.args, dataset="exportacao", produto="soja",
                    ano=2026, uf="MT", provider=provider)
        primeiro = coletar_mercado_agrobr(**opts)
        segundo = coletar_mercado_agrobr(**opts)
        self.assertEqual(primeiro["novas_observacoes"], 2)
        self.assertEqual(segundo["novas_observacoes"], 0)
        self.assertEqual(primeiro["sha256"], segundo["sha256"])
        self.assertEqual(primeiro["payload"], "AGROBR_RESULTADO_NORMALIZADO, NÃO RAW DA FONTE")
        self.assertTrue(Path(primeiro["arquivo_raw"]).exists())
        dados = json.loads(Path(primeiro["arquivo_raw"]).read_text())
        self.assertEqual(dados["tipo"], "AGROBR_RESULTADO_NORMALIZADO")
        self.assertEqual(provider.calls[0][2], {"ano": 2026, "uf": "MT"})
        dataset_id = CONTRATOS["exportacao"][0]
        stage = self.root / "stage.jsonl"
        exp = exportar_jsonl(banco=self.args["banco"], destino=stage, dataset_id=dataset_id)
        self.assertEqual(exp["observacoes"], 2)
        linhas = [json.loads(x) for x in stage.read_text().splitlines()]
        self.assertEqual({x["unidade"] for x in linhas}, {"kg", "USD"})
        self.assertEqual({x["referencia"] for x in linhas}, {"2026-09-30"})
        self.assertTrue(all(x["natureza"] == "INFORMADO" for x in linhas))
        provider.rows = [linha_comex(fob=550)]
        terceiro = coletar_mercado_agrobr(**opts)
        self.assertEqual(terceiro["novas_observacoes"], 1)
        with sqlite3.connect(self.args["banco"]) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM snapshots WHERE dataset_id=?", (dataset_id,)
            ).fetchone()[0], 2)

    def test_importacao_preserva_frete_e_seguro_sem_misturar_fob(self):
        provider = FakeProvider([linha_comex(produto="milho", frete=50.1, seguro=6.2)],
                                Meta("comexstat", contract="1.2"))
        out = coletar_mercado_agrobr(**self.args, dataset="importacao",
                                    produto="milho", ano=2026, uf="MT", provider=provider)
        self.assertEqual(out["novas_observacoes"], 4)
        result = exportar_jsonl(
            banco=self.args["banco"], destino=self.root / "import.jsonl",
            dataset_id=CONTRATOS["importacao"][0])
        self.assertEqual(result["observacoes"], 4)
        dados = [json.loads(line) for line in (self.root / "import.jsonl").read_text().splitlines()]
        self.assertEqual({r["campos"]["metrica"] for r in dados},
                         {"kg_liquido", "valor_fob_usd", "valor_frete_usd", "valor_seguro_usd"})

    def test_cftc_saldo_negativo_e_data_referencia(self):
        provider = FakeProvider([linha_cftc()], Meta("cftc", contract="2.0"))
        out = coletar_mercado_agrobr(
            **self.args, dataset="posicionamento_fundos", produto="soja",
            inicio="2026-10-01", fim="2026-10-26", provider=provider)
        self.assertEqual(out["novas_observacoes"], 5)
        stage = self.root / "cot.jsonl"
        exp = exportar_jsonl(
            banco=self.args["banco"], destino=stage,
            dataset_id=CONTRATOS["posicionamento_fundos"][0])
        self.assertEqual(exp["observacoes"], 5)
        linhas = [json.loads(r) for r in stage.read_text().splitlines()]
        saldo = next(v for v in linhas if v["campos"]["metrica"] == "fundos_saldo")
        self.assertEqual(saldo["valor"], "-50")
        self.assertEqual(saldo["unidade"], "contratos")
        self.assertEqual(saldo["referencia"], "2026-10-20")
        self.assertIn("005602", saldo["identidade"])

    def test_fallback_abioove_e_licenca_cinza_bloqueados(self):
        for meta in (Meta("abiove"), Meta("comexstat", license="zona_cinza"),
                     Meta("comexstat", version="1.7.0")):
            with self.subTest(meta=meta.source), self.assertRaises((ErroAgrobrMercados, PermissionError)):
                coletar_mercado_agrobr(
                    **self.args, dataset="exportacao", produto="soja",
                    ano=2026, provider=FakeProvider([linha_comex(uf=None)], meta))
            self.assertFalse(self.args["banco"].exists())

    def test_entrada_fora_do_contrato_nao_grava(self):
        casos = [
            {"dataset": "exportacao", "produto": "fertilizantes", "ano": 2026},
            {"dataset": "exportacao", "produto": "soja", "ano": 2027},
            {"dataset": "importacao", "produto": "milho", "ano": 2026, "uf": "MATO GROSSO"},
            {"dataset": "posicionamento_fundos", "produto": "soja",
             "inicio": "2020-01-01", "fim": "2026-10-26"},
            {"dataset": "posicionamento_fundos", "produto": "soja",
             "inicio": "2026-10-20", "fim": "2026-10-01"},
        ]
        for k in casos:
            with self.subTest(k=k), self.assertRaises(ErroAgrobrMercados):
                coletar_mercado_agrobr(
                    **self.args, provider=FakeProvider([], Meta("comexstat")), **k)

    def test_rejeita_chave_duplicada_cot_incoerente_comex_negativo(self):
        casos = [
            ("exportacao", "soja", 2026, Meta("comexstat"),
             [linha_comex(), linha_comex()]),
            ("importacao", "soja", 2026, Meta("comexstat", contract="1.2"),
             [linha_comex(kg=-1)]),
            ("posicionamento_fundos", "soja", None, Meta("cftc", contract="2.0"),
             [{**linha_cftc(), "fundos_saldo": 100}]),
        ]
        for ds, produto, ano, meta, rows in casos:
            with self.subTest(ds=ds, rows=len(rows)), self.assertRaises(ErroAgrobrMercados):
                coletar_mercado_agrobr(**self.args, dataset=ds, produto=produto,
                    ano=ano, provider=FakeProvider(rows, meta))
            self.assertFalse(self.args["banco"].exists())

    def test_necessita_execucao_explicita(self):
        with self.assertRaises(PermissionError):
            coletar_mercado_agrobr(dataset="exportacao", produto="soja",
                                   ano=2026, banco=self.args["banco"],
                                   raw_dir=self.args["raw_dir"])


if __name__ == "__main__":
    unittest.main()
