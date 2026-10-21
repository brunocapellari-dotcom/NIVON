"""Testes inteiramente sinteticos do reconciliador PTAX, sem Cloud e sem Neon."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from ptax_neon_to_bigquery_jsonl import normalize
from reconcile_ptax_neon_bigquery import InvalidSnapshot, canonical_target, reconcile, main


def neon(**overrides):
    result = {
        "id": 12,
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
    result.update(overrides)
    return result


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.source = Path(self.folder.name) / "neon-private.jsonl"
        self.target = Path(self.folder.name) / "bq-private.jsonl"

    def write(self, sources, destinations):
        self.source.write_text("".join(json.dumps(r) + "\n" for r in sources), encoding="utf-8")
        self.target.write_text("".join(json.dumps(r) + "\n" for r in destinations), encoding="utf-8")

    def test_identical_migration_snapshot_only_never_cutover(self):
        a = neon()
        b = neon(id=13, currency="EUR", buy_brl="6.15", sell_brl="6.16")
        self.write([a, b], [normalize(a), normalize(b)])
        result = reconcile(self.source, self.target)
        self.assertEqual(result["source_records"], 2)
        self.assertEqual(result["matching_records"], 2)
        self.assertEqual(result["missing_in_target"], 0)
        self.assertEqual(result["unexpected_in_target"], 0)
        self.assertTrue(result["local_snapshot_consistent"])
        self.assertFalse(result["cutover_approved"])
        self.assertFalse(result["backup_restore_verified"])
        self.assertFalse(result["cloud_project_access_verified"])
        self.assertEqual(result["source_currency_counts"], {"USD": 1, "EUR": 1})
        self.assertEqual(len(result["source_file_sha256"]), 64)
        self.assertNotIn("5.123", json.dumps(result))
        self.assertNotIn("13:03:07", json.dumps(result))

    def test_missing_quote_detected(self):
        a = neon()
        b = neon(id=13, currency="EUR", buy_brl="6.15", sell_brl="6.16")
        self.write([a, b], [normalize(a)])
        result = reconcile(self.source, self.target)
        self.assertEqual(result["missing_in_target"], 1)
        self.assertFalse(result["local_snapshot_consistent"])

    def test_unexpected_quote_detected(self):
        a = neon()
        b = neon(id=13, currency="EUR", buy_brl="6.15", sell_brl="6.16")
        self.write([a], [normalize(a), normalize(b)])
        result = reconcile(self.source, self.target)
        self.assertEqual(result["unexpected_in_target"], 1)
        self.assertFalse(result["local_snapshot_consistent"])

    def test_same_quote_with_updated_metadata_detected(self):
        a = neon()
        b = neon(last_verified_at="2026-10-21T12:10:00-04:00")
        self.write([a], [normalize(b)])
        result = reconcile(self.source, self.target)
        self.assertEqual(result["changed_records"], 1)
        self.assertFalse(result["local_snapshot_consistent"])

    def test_price_revision_detected_as_new_quote_id(self):
        a = neon()
        b = neon(buy_brl="5.123456788")
        self.write([a], [normalize(b)])
        result = reconcile(self.source, self.target)
        self.assertEqual(result["missing_in_target"], 1)
        self.assertEqual(result["unexpected_in_target"], 1)

    def test_duplicate_keys_never_count_as_valid(self):
        a = neon()
        self.write([a, a], [normalize(a), normalize(a)])
        result = reconcile(self.source, self.target)
        self.assertEqual(result["source_duplicate_keys"], 1)
        self.assertEqual(result["target_duplicate_keys"], 1)
        self.assertFalse(result["local_snapshot_consistent"])

    def test_zero_zero_not_success(self):
        self.write([], [])
        result = reconcile(self.source, self.target)
        self.assertEqual(result["source_records"], 0)
        self.assertFalse(result["local_snapshot_consistent"])

    def test_tampered_destination_hash_fails_closed(self):
        a = neon()
        dest = normalize(a)
        dest["record_sha256"] = "0" * 64
        self.write([a], [dest])
        with self.assertRaises(InvalidSnapshot):
            reconcile(self.source, self.target)

    def test_tampered_destination_price_fails_closed(self):
        a = neon()
        dest = normalize(a)
        dest["buy_brl"] = "7.0"
        self.write([a], [dest])
        with self.assertRaises(InvalidSnapshot):
            reconcile(self.source, self.target)

    def test_bq_numeric_and_timestamp_serialization(self):
        a = neon()
        dest = normalize(a)
        dest["buy_brl"] = 5.123456789  # JSON number parsed via Decimal
        dest["source_neon_row_id"] = "12"  # BQ JSON INT64 representation
        dest["first_collected_at"] = "2026-10-21 14:10:00 UTC"
        dest["last_verified_at"] = "2026-10-21 15:10:00 UTC"
        # A leitura do arquivo JSONL converte decimais para Decimal antes de validar.
        self.write([a], [dest])
        self.assertTrue(reconcile(self.source, self.target)["local_snapshot_consistent"])

    def test_extra_unexpected_target_field_rejected(self):
        a = neon()
        dest = normalize(a)
        dest["unexpected"] = "unsafe"
        self.write([a], [dest])
        with self.assertRaises(InvalidSnapshot):
            reconcile(self.source, self.target)

    def test_same_input_file_is_rejected(self):
        a = neon()
        self.write([a], [normalize(a)])
        with self.assertRaises(InvalidSnapshot):
            reconcile(self.source, self.source)

    def test_invalid_source_line_rejected(self):
        a = neon(currency="GBP")
        self.write([a], [normalize(neon())])
        with self.assertRaises(InvalidSnapshot):
            reconcile(self.source, self.target)

    def test_invalid_timezone_target_rejected(self):
        a = neon()
        dest = normalize(a)
        dest["first_collected_at"] = "2026-10-21T14:10:00"
        self.write([a], [dest])
        with self.assertRaises(InvalidSnapshot):
            reconcile(self.source, self.target)

    def test_duplicate_source_rows_cannot_mask_missing(self):
        a = neon()
        b = neon(id=13, currency="EUR", buy_brl="6.15", sell_brl="6.16")
        self.write([a, a, b], [normalize(a), normalize(b)])
        result = reconcile(self.source, self.target)
        self.assertFalse(result["local_snapshot_consistent"])
        self.assertEqual(result["source_duplicate_keys"], 1)

    def test_cli_success_only_for_valid_local_snapshots(self):
        a = neon()
        self.write([a], [normalize(a)])
        with mock.patch("sys.stdout"):
            self.assertEqual(main(["--source-neon", str(self.source), "--target-bigquery", str(self.target)]), 0)
        self.write([a], [])
        with unittest.mock.patch("sys.stdout"):
            self.assertEqual(main(["--source-neon", str(self.source), "--target-bigquery", str(self.target)]), 4)


if __name__ == "__main__":
    unittest.main()
