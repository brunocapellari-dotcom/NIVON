"""Provas de migracao PTAX offline, sinteticas, sem conectar Neon ou GCP."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ptax_neon_to_bigquery_jsonl.py"
_spec = importlib.util.spec_from_file_location("nivon_ptax_bigquery_copy", SCRIPT)
assert _spec and _spec.loader
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def sample(**changes):
    row = {
        "id": 7,
        "currency": "USD",
        "reference_date": "2026-10-21",
        "quote_time_original": "2026-10-21 13:03:07",
        "bulletin_type": "COTACAO_DOLAR_DIARIA",
        "buy_brl": "5.123456789",
        "sell_brl": "5.123456790",
        "unit": "BRL/USD",
        "source": "Banco Central do Brasil / PTAX",
        "license": "ODbL",
        "published_at": None,
        "first_collected_at": "2026-10-21T10:10:00-04:00",
        "last_verified_at": "2026-10-21T11:10:00-04:00",
        "observation_kind": "INFORMADO",
    }
    row.update(changes)
    return row


class PtAxExportTests(unittest.TestCase):
    def test_preserves_semantics_and_undefined_publication(self):
        output = m.normalize(sample())
        self.assertEqual(output["currency"], "USD")
        self.assertEqual(output["reference_date"], "2026-10-21")
        self.assertEqual(output["quote_time_original"], "2026-10-21 13:03:07")
        self.assertEqual(output["bulletin_type"], "COTACAO_DOLAR_DIARIA")
        self.assertEqual(output["buy_brl"], "5.123456789")
        self.assertEqual(output["sell_brl"], "5.12345679")
        self.assertIsNone(output["published_at"])
        self.assertIsNone(output["origem_sha256"])
        self.assertEqual(output["observation_kind"], "INFORMADO")
        self.assertEqual(output["first_collected_at"], "2026-10-21T14:10:00Z")
        self.assertEqual(output["last_verified_at"], "2026-10-21T15:10:00Z")
        self.assertEqual(output["migration_schema_version"], "1.0.0")
        self.assertEqual(output["quality_status"], "NEON_EXPORT_UNVERIFIED")
        self.assertEqual(len(output["quote_id"]), 64)
        self.assertEqual(len(output["record_sha256"]), 64)

    def test_vintage_distinguishes_price_revisions(self):
        a = m.normalize(sample())
        b = m.normalize(sample(buy_brl="5.123456788"))
        self.assertNotEqual(a["quote_id"], b["quote_id"])
        self.assertEqual(a["vintage_id"], a["quote_id"])

    def test_business_key_equivalent_numeric_formats(self):
        a = m.normalize(sample(buy_brl="5.100000000", sell_brl="5.200000000"))
        b = m.normalize(sample(buy_brl="5.1", sell_brl="5.2", id=8))
        self.assertEqual(a["quote_id"], b["quote_id"])
        self.assertNotEqual(a["record_sha256"], b["record_sha256"])

    def test_bulletin_time_cannot_be_overwritten(self):
        a = m.normalize(sample())
        b = m.normalize(sample(quote_time_original="2026-10-21 13:05:07"))
        self.assertNotEqual(a["quote_id"], b["quote_id"])

    def test_missing_publication_field_accepted_as_null(self):
        row = sample()
        del row["published_at"]
        self.assertIsNone(m.normalize(row)["published_at"])

    def test_rejects_timezone_naive_timestamps(self):
        with self.assertRaises(m.InvalidQuote):
            m.normalize(sample(first_collected_at="2026-10-21T10:10:00"))

    def test_rejects_backward_verification(self):
        with self.assertRaises(m.InvalidQuote):
            m.normalize(sample(last_verified_at="2026-10-21T09:10:00-04:00"))

    def test_rejects_unexpected_columns_and_invalid_nature(self):
        with self.assertRaises(m.InvalidQuote):
            m.normalize(sample(secret="not-allowed"))
        with self.assertRaises(m.InvalidQuote):
            m.normalize(sample(observation_kind="PROJETADO"))

    def test_rejects_out_of_range_decimals(self):
        for value in ("0", "-1", "1000000000.0", "5.1234567891", "NaN", "Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(m.InvalidQuote):
                    m.normalize(sample(buy_brl=value))

    def test_local_file_conversion_and_summary_only(self):
        with tempfile.TemporaryDirectory() as folder:
            input_path = Path(folder) / "neon-private.jsonl"
            output_path = Path(folder) / "bigquery-private.jsonl"
            eur = sample(id=8, currency="EUR", buy_brl="6.11", sell_brl="6.12")
            input_path.write_text(
                json.dumps(sample()) + "\n" + json.dumps(eur) + "\n", encoding="utf-8"
            )
            report = m.convert(input_path, output_path)
            self.assertEqual(report["quote_count"], 2)
            self.assertEqual(report["count_by_currency"], {"USD": 1, "EUR": 1})
            self.assertFalse(report["uploaded_to_cloud"])
            self.assertFalse(report["export_reconciled_against_neon"])
            self.assertFalse(report["raw_odata_checksum_available"])
            data = [json.loads(line) for line in output_path.read_text().splitlines()]
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["currency"], "USD")
            self.assertEqual(data[1]["currency"], "EUR")
            self.assertNotIn("buy_brl", report)
            self.assertNotIn("sell_brl", report)
            if os.name != "nt":
                self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(m.InvalidQuote):
                m.convert(input_path, output_path)

    def test_duplicate_business_key_aborts_atomic_output(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "i.jsonl"
            out = Path(folder) / "o.jsonl"
            p.write_text(json.dumps(sample()) + "\n" + json.dumps(sample(id=9)) + "\n")
            with self.assertRaises(m.InvalidQuote):
                m.convert(p, out)
            self.assertFalse(out.exists())

    def test_invalid_second_line_leaves_no_partial_export(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "i.jsonl"
            out = Path(folder) / "o.jsonl"
            p.write_text(json.dumps(sample()) + "\n" + json.dumps(sample(currency="GBP")) + "\n")
            with self.assertRaises(m.InvalidQuote):
                m.convert(p, out)
            self.assertFalse(out.exists())

    def test_never_write_output_inside_repo(self):
        with self.assertRaises(m.InvalidQuote):
            m.convert(Path("/tmp/input-neon.jsonl"), ROOT / "should_not_be_created.jsonl")

    def test_cli_without_mandatory_args_is_inert(self):
        with self.assertRaises(SystemExit) as ctx:
            m.main([])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
