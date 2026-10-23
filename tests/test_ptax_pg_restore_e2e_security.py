"""Contrato de segurança da integração PostgreSQL 17 em CI sem Neon/GCP."""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ptax_pg_restore_synthetic_e2e.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "ptax-postgres-restore-ci.yml"
FIXTURE = ROOT / "tests" / "fixtures" / "ptax_postgres17_synthetic.sql"


class SyntheticPgRestoreGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.sql = FIXTURE.read_text(encoding="utf-8")

    def test_shell_syntax_and_default_inert(self):
        if not shutil.which("bash"):
            self.skipTest("bash unavailable")
        parse = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True)
        self.assertEqual(parse.returncode, 0)
        run = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn("--run-synthetic", run.stderr)

    def test_runner_is_fully_isolated(self):
        self.assertIn("--network none", self.script)
        self.assertIn("docker run --detach --rm", self.script)
        self.assertIn("docker rm --force", self.script)
        self.assertIn("trap cleanup EXIT", self.script)
        self.assertNotIn("-p 5432:", self.script)
        self.assertNotIn("--publish", self.script)
        self.assertNotIn("--volume", self.script)
        self.assertNotIn("PGSERVICE", self.script)
        self.assertNotIn("DATABASE_URL", self.script)

    def test_real_restore_only_into_ephemeral_test_database(self):
        self.assertIn("createdb -U postgres nivon_restore_check", self.script)
        self.assertIn("--dbname=nivon_restore_check", self.script)
        self.assertIn("pg_dump -U postgres", self.script)
        self.assertIn("pg_restore -U postgres", self.script)
        self.assertIn("--serializable-deferrable", self.script)
        self.assertNotIn("pg_restore --clean", self.script)
        self.assertNotIn("pg_restore --create", self.script)
        self.assertNotIn("pg_restore -d nivon", self.script)

    def test_three_tables_and_identity_sequences(self):
        for name in ("nivon_ptax_quotes", "nivon_ptax_runs",
                     "nivon_ptax_checkpoints", "nivon_ptax_quotes_id_seq",
                     "nivon_ptax_runs_id_seq"):
            self.assertIn("--table=public." + name, self.script)
        self.assertIn("source_fingerprint", self.script)
        self.assertIn("restored_fingerprint", self.script)
        self.assertIn("3:2:2", self.script)
        self.assertIn("production_restore_verified=false", self.script)

    def test_fixture_is_synthetic_and_has_revisions(self):
        self.assertIn("TESTE SINTETICO", self.sql)
        self.assertIn("TEST-ONLY", self.sql)
        self.assertIn("6.123456789", self.sql)
        self.assertIn("6.123456788", self.sql)
        self.assertNotIn("DATABASE_URL", self.sql)
        self.assertEqual(self.sql.count("CREATE TABLE"), 3)

    def test_audit_reads_same_canonical_sql_both_sides(self):
        self.assertEqual(
            self.script.count("< database/neon_ptax_readonly_audit.sql"), 2
        )
        self.assertIn("audit_normalize", self.script)
        self.assertIn("source_audit", self.script)
        self.assertIn("restored_audit", self.script)
        self.assertIn('obj=obj.get("source_audit_manifest",obj)', self.script)
        self.assertIn('obj.pop("snapshot_timestamp_utc",None)', self.script)
        self.assertIn('obj["duplicate_business_keys"]==0', self.script)
        self.assertIn('obj["invalid_prices"]==0', self.script)

    def test_source_and_restored_schema_indexes_constraints_matched(self):
        self.assertIn("'indexes',(SELECT jsonb_agg", self.script)
        self.assertIn("'constraints',(SELECT jsonb_agg", self.script)
        self.assertIn("pg_indexes", self.script)
        self.assertIn("pg_get_constraintdef", self.script)
        self.assertIn("source_fingerprint", self.script)
        self.assertIn("restored_fingerprint", self.script)
        for index in (
            "idx_nivon_ptax_quotes_latest",
            "idx_nivon_ptax_runs_by_date",
            "idx_nivon_ptax_checkpoints_latest",
        ):
            self.assertIn(index, self.sql)

    def test_workflow_only_pull_requests_and_read_only(self):
        self.assertIn("  pull_request:", self.workflow)
        self.assertIn("  contents: read", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)
        self.assertIn("timeout-minutes: 8", self.workflow)
        self.assertIn("--run-synthetic", self.workflow)
        self.assertNotIn("pull_request_target:", self.workflow)
        self.assertNotIn("  push:", self.workflow)
        self.assertNotIn("secrets.", self.workflow)
        self.assertNotIn("github.token", self.workflow)
        self.assertNotIn("actions/upload-artifact", self.workflow)
        self.assertNotIn("gcloud", self.workflow)
        self.assertNotIn("neon.tech", self.workflow)


if __name__ == "__main__":
    unittest.main()
