"""Testes somente offline do contrato de janelas PTAX, sem Neon nem GCP."""
from __future__ import annotations
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_ptax_backfill_health.py"
SQL = ROOT / "database" / "neon_ptax_backfill_health.sql"
spec = importlib.util.spec_from_file_location("nivon_ptax_backfill_health", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture():
    row = {
        "daily_errors": 0, "stored_quotes": 888, "backfill_errors": 0,
        "last_checkpoint": "2026-10-22T00:05:03Z",
        "pending_windows": 73, "backfill_fetched": 853,
        "expected_windows": 81, "next_pending_end": "2020-10-05",
        "completed_windows": 8,
        "last_backfill_run": "2026-10-22T00:05:03Z",
        "next_pending_start": "2020-09-05",
        "newest_observed_date": "2026-10-21",
        "farthest_completed_end": "2020-09-04",
        "stored_reference_dates": 178,
        "gcp_migration_authorized": False,
        "non_historical_checkpoints": 1,
        "contiguous_completed_through": "2020-09-04",
        "historical_source_coverage_verified": False,
        "last_daily_run": "2026-10-21T17:19:02Z",
    }
    return {"backfill_health": {
        "status": "OBSERVED_CHECKPOINTS_NOT_FULL_SOURCE_COVERAGE",
        "contract": "NIVON_PTAX_BACKFILL_HEALTH_V1",
        "by_currency": [dict(row,currency="EUR"),dict(row,currency="USD",stored_quotes=178,backfill_fetched=171)],
        "bigquery_loaded": False, "observed_at_utc": "2026-10-22T00:50:44Z",
        "cutover_approved": False, "historical_start": "2020-01-01",
        "nominal_window_days": 31, "as_of_sao_paulo_date": "2026-10-21",
        "external_backup_verified": False
    }}


class BackfillHealthTests(unittest.TestCase):
    def test_valid_report_yields_incomplete_9_9_percent(self):
        r = m.analyze(fixture())
        self.assertEqual(r["status"], "HISTORICAL_BACKFILL_IN_PROGRESS")
        self.assertFalse(r["history_complete"])
        self.assertFalse(r["live_price_freshness_verified"])
        self.assertFalse(r["cutover_allowed"])
        self.assertEqual([x["currency"] for x in r["currencies"]], ["EUR","USD"])
        for x in r["currencies"]:
            self.assertEqual((x["planned_windows"],x["completed_windows"],x["pending_windows"]), (81,8,73))
            self.assertEqual(x["window_progress_pct"],9.9)
            self.assertEqual(x["next_window"],{"start":"2020-09-05","end":"2020-10-05"})
            self.assertIn("HISTORICAL_WINDOWS_PENDING",x["warnings"])
            self.assertFalse(x["source_calendar_completeness_proven"])
            self.assertFalse(x["migration_allowed"])
        self.assertNotIn("buy_brl",json.dumps(r))

    def test_accepts_direct_object_without_envelope(self):
        self.assertEqual(len(m.analyze(fixture()["backfill_health"])["currencies"]),2)

    def test_rejects_missing_or_duplicate_currencies(self):
        f=fixture();f["backfill_health"]["by_currency"].pop()
        with self.assertRaises(m.HealthInvalid):m.analyze(f)
        f=fixture();f["backfill_health"]["by_currency"][0]["currency"]="USD"
        with self.assertRaises(m.HealthInvalid):m.analyze(f)

    def test_rejects_inconsistent_counts(self):
        for field,value in [("pending_windows",72),("completed_windows",True),
                             ("expected_windows",82),("stored_reference_dates",999)]:
            with self.subTest(field=field):
                f=fixture();f["backfill_health"]["by_currency"][0][field]=value
                with self.assertRaises(m.HealthInvalid):m.analyze(f)

    def test_rejects_invalid_next_start_end_and_watermark(self):
        for field,value in [
            ("next_pending_start","2020-09-06"),("next_pending_end","2020-10-04"),
            ("contiguous_completed_through","2020-08-04"),
        ]:
            with self.subTest(field=field):
                f=fixture();f["backfill_health"]["by_currency"][0][field]=value
                with self.assertRaises(m.HealthInvalid):m.analyze(f)

    def test_rejects_naive_timestamp_and_future_reference_date(self):
        f=fixture();f["backfill_health"]["by_currency"][0]["last_backfill_run"]="2026-10-22T00:05:03"
        with self.assertRaises(m.HealthInvalid):m.analyze(f)
        f=fixture();f["backfill_health"]["by_currency"][0]["newest_observed_date"]="2026-10-23"
        with self.assertRaises(m.HealthInvalid):m.analyze(f)

    def test_rejects_all_premature_external_gates(self):
        for key in ("external_backup_verified","bigquery_loaded","cutover_approved"):
            f=fixture();f["backfill_health"][key]=True
            with self.subTest(key=key),self.assertRaises(m.HealthInvalid):m.analyze(f)
        f=fixture();f["backfill_health"]["by_currency"][0]["gcp_migration_authorized"]=True
        with self.assertRaises(m.HealthInvalid):m.analyze(f)

    def test_out_of_order_checkpoint_detected_without_false_completion(self):
        f=fixture();item=f["backfill_health"]["by_currency"][0]
        item["completed_windows"]=9;item["pending_windows"]=72
        item["farthest_completed_end"]="2020-11-05"
        r=m.analyze(f)
        self.assertIn("OUT_OF_ORDER_COMPLETED_WINDOWS",r["currencies"][0]["warnings"])
        self.assertFalse(r["history_complete"])

    def test_errors_and_stale_backfill_warn(self):
        f=fixture();item=f["backfill_health"]["by_currency"][0]
        item["backfill_errors"]=1
        item["last_backfill_run"]="2026-10-21T18:00:00Z"
        warnings=m.analyze(f)["currencies"][0]["warnings"]
        self.assertIn("BACKFILL_LAST_RUN_OLDER_THAN_3H",warnings)
        self.assertIn("COLLECTOR_REPORTED_ERRORS",warnings)

    def test_all_checkpoints_still_not_source_completeness(self):
        f=fixture()
        for x in f["backfill_health"]["by_currency"]:
            x["completed_windows"]=81;x["pending_windows"]=0
            x["next_pending_start"]=None;x["next_pending_end"]=None
            x["contiguous_completed_through"]="2026-10-21"
            x["farthest_completed_end"]="2026-10-21"
        r=m.analyze(f)
        self.assertEqual(r["status"],"CHECKPOINTS_COMPLETE_SOURCE_NOT_AUDITED")
        self.assertFalse(r["history_complete"])

    def test_rejects_forged_complete_report(self):
        f=fixture();f["backfill_health"]["by_currency"][0]["historical_source_coverage_verified"]=True
        with self.assertRaises(m.HealthInvalid):m.analyze(f)

    def test_sql_is_read_only_and_uses_sao_paulo_calendar(self):
        sql="\n".join(line for line in SQL.read_text(encoding="utf-8").splitlines()
                      if not line.strip().startswith("--"))
        self.assertIn("America/Sao_Paulo",sql)
        self.assertIn("generate_series(",sql)
        self.assertIn("public.nivon_ptax_checkpoints",sql)
        self.assertIn("public.nivon_ptax_runs",sql)
        self.assertIn("public.nivon_ptax_quotes",sql)
        self.assertEqual(sql.count(";"),1)
        self.assertIsNone(re.search(r"\b(?:INSERT|UPDATE|DELETE|TRUNCATE|DROP|ALTER|MERGE|GRANT|REVOKE|CREATE)\b",sql,re.I))

    def test_cli_good_and_bad_json_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp=Path(tmp)/"manifest.json"
            inp.write_text(json.dumps(fixture()),encoding="utf-8")
            with mock.patch("sys.stdout"):
                self.assertEqual(m.main(["--input",str(inp)]),0)
            inp.write_text('{"bad":true}',encoding="utf-8")
            with mock.patch("sys.stderr"):
                self.assertEqual(m.main(["--input",str(inp)]),3)


if __name__=="__main__":
    unittest.main()
