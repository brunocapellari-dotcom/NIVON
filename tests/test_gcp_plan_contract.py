"""Regressões offline da decisão Google Cloud; nenhum login, HTTP ou provisionamento."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "config" / "gcp_data_platform.v1.json"
DDL = ROOT / "database" / "bigquery" / "nivon_initial_schema.sql"


class GcpPlanContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(PLAN.read_text(encoding="utf-8"))
        cls.sql = DDL.read_text(encoding="utf-8")

    def test_no_unapproved_cloud_use(self):
        plan = self.plan
        self.assertEqual(plan["state"], "PLAN_ONLY_NO_CLOUD_RESOURCES_CREATED")
        self.assertIsNone(plan["gcp_project_id"])
        self.assertFalse(plan["billing"]["paid_use_approved"])
        self.assertTrue(plan["billing"]["zero_cost_required"])
        self.assertTrue(plan["billing"]["deploy_blocked_until_cost_controls_verified"])
        for key in ("bigquery", "cloud_storage", "cloud_run"):
            self.assertFalse(plan["services"][key]["enabled"])
        self.assertFalse(plan["services"]["cloud_storage"]["public_access_allowed"])
        self.assertFalse(plan["services"]["cloud_run"]["automatic_scheduler_enabled"])

    def test_single_region_and_portability(self):
        p = self.plan
        self.assertEqual(p["location"], "us-central1")
        self.assertIsNone(p["services"]["cloud_storage"]["bucket_name"])
        self.assertIn("raw/", p["services"]["cloud_storage"]["prefixes"])
        self.assertTrue(p["prior_systems"]["neon_ptax"]["migrate_after_backup_and_reconciliation"])
        self.assertEqual(p["prior_systems"]["neon_ptax"]["mode"], "KEEP_RUNNING_UNTIL_VALIDATED_CUTOVER")
        self.assertEqual(p["prior_systems"]["duckdb"]["mode"], "KEEP_ANALYTICAL_PARQUET_PORTABILITY")

    def test_provenance_and_gates(self):
        p = self.plan
        self.assertEqual(
            set(p["provenance"]["date_fields"]),
            {"competencia", "data_referencia", "data_publicacao", "data_coleta"},
        )
        self.assertTrue(p["provenance"]["unknown_published_at_must_remain_null"])
        self.assertTrue(p["provenance"]["require_individual_source_storage_permission"])
        self.assertTrue(p["provenance"]["never_publish_synthetic_as_real"])
        self.assertTrue(all(p["gates"].values()))

    def test_bigquery_tables_temporal_partitioning(self):
        sql = self.sql
        self.assertIn("${PROJECT_ID}", sql)
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"), 4)
        self.assertGreaterEqual(sql.count("require_partition_filter = TRUE"), 4)
        self.assertGreaterEqual(sql.count("CLUSTER BY"), 4)
        for column in (
            "fonte_id", "dataset_id", "origem_sha256", "vintage_id",
            "competencia", "data_referencia", "data_publicacao", "data_coleta",
        ):
            self.assertIn(column, sql)
        self.assertIn("PARTITION BY data_referencia", sql)
        self.assertIn("PARTITION BY DATE(data_coleta)", sql)
        self.assertIn("emitida_em TIMESTAMP NOT NULL", sql)

    def test_no_secrets_or_automatic_deploy(self):
        text = PLAN.read_text(encoding="utf-8") + self.sql
        for forbidden in ("BEGIN PRIVATE KEY", "DATABASE_URL=", "gcloud auth activate-service-account"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
