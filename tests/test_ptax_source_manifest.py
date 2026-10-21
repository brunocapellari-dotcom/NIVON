"""Regressoes offline da evidência agregada Neon PTAX (sem dados de mercado)."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "validate_ptax_source_manifest.py"
S_Q = ROOT / "database" / "neon_ptax_readonly_audit.sql"
spec = importlib.util.spec_from_file_location("ptax_manifest_guard", SRC)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    return {
        "contract": "NIVON_PTAX_SOURCE_AUDIT_V1",
        "snapshot_timestamp_utc": "2026-10-21T22:58:24Z",
        "source": "Neon NIVON-PTAX-OPERACIONAL/public.nivon_ptax_quotes",
        "quote_count": 796, "run_count": 14, "run_errors": 0,
        "run_running": 0, "run_successful": 14, "checkpoint_count": 14,
        "invalid_timestamps": 0, "invalid_currency": 0, "invalid_prices": 0,
        "suspect_publication": 0, "duplicate_business_keys": 0,
        "by_currency": [
            {"currency": "EUR", "quotes": 663, "reference_days": 133,
             "first_reference": "2020-01-02", "last_reference": "2026-10-21",
             "last_verified": "2026-10-21T22:05:03Z"},
            {"currency": "USD", "quotes": 133, "reference_days": 133,
             "first_reference": "2020-01-02", "last_reference": "2026-10-21",
             "last_verified": "2026-10-21T22:05:02Z"},
        ],
        "by_year": [
            {"currency": "EUR", "year": 2020, "quotes": 628, "reference_days": 126},
            {"currency": "EUR", "year": 2026, "quotes": 35, "reference_days": 7},
            {"currency": "USD", "year": 2020, "quotes": 126, "reference_days": 126},
            {"currency": "USD", "year": 2026, "quotes": 7, "reference_days": 7},
        ],
        "origin_coverage_complete": False,
        "external_backup_restored": False,
        "bigquery_migrated": False,
        "migration_authorized": False,
    }


class PtaxSourceManifestTests(unittest.TestCase):
    def test_actual_shape_passes_basic_checks_but_blocks_cutover(self):
        report = module.analyze(fixture())
        self.assertTrue(report["basic_source_integrity_passed"])
        self.assertEqual(report["currency_quotes"], {"USD": 133, "EUR": 663})
        self.assertEqual(report["quotes"], 796)
        self.assertEqual(report["missing_intermediate_years"]["USD"], [2021, 2022, 2023, 2024, 2025])
        self.assertEqual(report["missing_intermediate_years"]["EUR"], [2021, 2022, 2023, 2024, 2025])
        self.assertFalse(report["historical_coverage_verified"])
        self.assertFalse(report["migration_or_cutover_approved"])
        self.assertEqual(report["recommendation"], "BACKFILL_AND_BACKUP_REQUIRED")

    def test_accepts_single_column_sql_envelope(self):
        response = module.analyze({"source_audit_manifest": fixture()})
        self.assertEqual(response["quotes"], 796)

    def test_reject_total_mismatch(self):
        case = fixture()
        case["quote_count"] = 795
        with self.assertRaises(module.ManifestError):
            module.analyze(case)

    def test_reject_currency_duplicates(self):
        case = fixture()
        case["by_currency"][1]["currency"] = "EUR"
        with self.assertRaises(module.ManifestError):
            module.analyze(case)

    def test_reject_broken_year_sums(self):
        case = fixture()
        case["by_year"][2]["quotes"] = 125
        with self.assertRaises(module.ManifestError):
            module.analyze(case)

    def test_reject_unknown_source(self):
        case = fixture()
        case["source"] = "untrusted"
        with self.assertRaises(module.ManifestError):
            module.analyze(case)

    def test_reject_premature_coverage_claim(self):
        for k in ("origin_coverage_complete", "bigquery_migrated", "external_backup_restored", "migration_authorized"):
            case = fixture()
            case[k] = True
            with self.subTest(k=k), self.assertRaises(module.ManifestError):
                module.analyze(case)

    def test_reject_invalid_dates(self):
        case = fixture()
        case["by_currency"][1]["first_reference"] = "2020-99-99"
        with self.assertRaises(module.ManifestError):
            module.analyze(case)

    def test_reject_inconsistent_run_status(self):
        case = fixture()
        case["run_errors"] = 10
        with self.assertRaises(module.ManifestError):
            module.analyze(case)

    def test_error_count_does_not_fake_success(self):
        case = fixture()
        case["run_errors"] = 1
        case["run_successful"] = 13
        r = module.analyze(case)
        self.assertFalse(r["basic_source_integrity_passed"])
        self.assertFalse(r["migration_or_cutover_approved"])

    def test_checkpoint_count_may_exceed_runs(self):
        case = fixture()
        case["checkpoint_count"] = 100
        self.assertTrue(module.analyze(case)["basic_source_integrity_passed"])

    def test_future_all_years_does_not_auto_grant_completeness(self):
        case = fixture()
        case["by_year"] = [
            {"currency": c, "year": y, "quotes": 1, "reference_days": 1}
            for c in ("EUR", "USD") for y in range(2020, 2027)
        ]
        for d in case["by_currency"]:
            d["quotes"] = 7
            d["reference_days"] = 7
        case["quote_count"] = 14
        result = module.analyze(case)
        self.assertEqual(result["missing_intermediate_years"], {"USD": [], "EUR": []})
        self.assertFalse(result["historical_coverage_verified"])

    def test_reject_negative_and_bool_counters(self):
        for wrong in (-1, True, "5"):
            case = fixture()
            case["quote_count"] = wrong
            with self.subTest(value=wrong), self.assertRaises(module.ManifestError):
                module.analyze(case)

    def test_readonly_sql_contains_no_mutations(self):
        import re
        sql = S_Q.read_text(encoding="utf-8")
        statements = "\n".join(
            line for line in sql.splitlines() if not line.lstrip().startswith("--")
        )
        self.assertIn("jsonb_build_object", statements)
        self.assertIn("COUNT(DISTINCT reference_date)", statements)
        self.assertIn("public.nivon_ptax_quotes", statements)
        self.assertIn("public.nivon_ptax_runs", statements)
        self.assertIn("public.nivon_ptax_checkpoints", statements)
        self.assertIsNone(re.search(r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|MERGE|TRUNCATE|GRANT|REVOKE)\b", statements, re.I))
        self.assertEqual(statements.count(";"), 1)

    def test_cli_manifest_validation_offline(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "manifest.json"
            inp.write_text(json.dumps(fixture()), encoding="utf-8")
            with mock.patch("sys.stdout"):
                self.assertEqual(module.main(["--input", str(inp)]), 0)
            inp.write_text('{"invalid": true}', encoding="utf-8")
            with mock.patch("sys.stderr"):
                self.assertEqual(module.main(["--input", str(inp)]), 3)


if __name__ == "__main__":
    unittest.main()
