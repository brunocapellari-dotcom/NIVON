"""E2E sintético em lote: ledger, falha, idempotência e restore independente."""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nivon import infra_offline_pipeline as batch
from nivon.infra_job_ledger import abrir_ledger, resumo


class TestBatchPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "state"
        self.back = Path(self.tmp.name) / "back"
        self.restored = Path(self.tmp.name) / "restored"
        for p in (self.root, self.back, self.restored):
            p.mkdir(mode=0o700)

    @staticmethod
    def fake_forecast(raw, key):
        assert json.loads(raw)["job_key"] == key
        n = batch.JOB_KEYS.index(key)
        return [float(8 + n), float(8 + n)]

    def verify(self, where):
        with closing(abrir_ledger(where / "jobs.sqlite")) as db:
            return batch._verify_files(where, db)

    def test_three_jobs_reentrant_no_duplicate(self):
        with patch.object(batch, "_forecast", self.fake_forecast):
            self.assertEqual(batch._prepare(self.root)["created"], 3)
            self.assertEqual(batch._prepare(self.root)["created"], 0)
            self.assertEqual(batch._process(self.root, interrupt=False)["processed"], 3)
            self.assertEqual(batch._process(self.root, interrupt=False)["processed"], 0)
            self.assertEqual(self.verify(self.root), 3)
            with closing(abrir_ledger(self.root / "jobs.sqlite")) as db:
                self.assertEqual(resumo(db)["contagens"]["SUCCEEDED"], 3)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM nivon_job_event "
                    "WHERE event='STARTED'").fetchone()[0], 3)

    def test_crash_and_explicit_synthetic_reconciliation(self):
        batch._prepare(self.root)
        with patch.object(batch, "_forecast", self.fake_forecast):
            result = batch._process(self.root, interrupt=True)
            self.assertTrue(result["requires_reconciliation"])
            with self.assertRaises(batch.PipelineBlocked):
                batch._process(self.root, interrupt=False)
            self.assertEqual(batch._reconcile(self.root)["explicit_requeued"], 1)
            self.assertEqual(batch._process(self.root, interrupt=False)["processed"], 3)
            with closing(abrir_ledger(self.root / "jobs.sqlite")) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM nivon_job_event "
                    "WHERE event='EXPLICIT_SYNTHETIC_REQUEUE'").fetchone()[0], 1)
                self.assertEqual(resumo(db)["contagens"]["UNCERTAIN"], 0)

    def test_backup_full_restore_and_no_replay(self):
        batch._prepare(self.root)
        with patch.object(batch, "_forecast", self.fake_forecast):
            batch._process(self.root, interrupt=False)
        self.assertEqual(batch._backup(self.root, self.back)["files"], 7)
        self.assertEqual(batch._restore(self.restored, self.back)["restored_jobs"], 3)
        self.assertEqual(self.verify(self.restored), 3)
        with patch.object(batch, "_forecast", self.fake_forecast):
            self.assertEqual(batch._process(self.restored, interrupt=False)["processed"], 0)

    def test_corrupted_artifact_prevents_restore(self):
        batch._prepare(self.root)
        with patch.object(batch, "_forecast", self.fake_forecast):
            batch._process(self.root, interrupt=False)
        batch._backup(self.root, self.back)
        (self.back / "outputs" / (batch.JOB_KEYS[0] + ".json")).write_text(
            '{"tampered":true}', encoding="utf-8")
        with self.assertRaises(batch.PipelineBlocked):
            batch._restore(self.restored, self.back)
        self.assertFalse((self.restored / "jobs.sqlite").exists())

    def test_private_root_and_real_flags_fail_closed(self):
        self.root.chmod(0o755)
        with self.assertRaises(batch.PipelineBlocked):
            batch._private(str(self.root))
        self.root.chmod(0o700)
        with patch.dict(os.environ, {"NIVON_COLLECTORS_ENABLED": "true"}):
            with self.assertRaises(batch.PipelineBlocked):
                batch.executar("prepare", root=str(self.root),
                               backup_root=None, interrupt=False)

    def test_no_uncertain_retry_if_output_exists(self):
        batch._prepare(self.root)
        batch._process(self.root, interrupt=True)
        batch._write_once(self.root / "outputs" / (batch.JOB_KEYS[0] + ".json"),
                          b'{"output":"unknown"}')
        with self.assertRaises(batch.PipelineBlocked):
            batch._reconcile(self.root)

    def test_existing_ci_reuses_images_and_no_deploy(self):
        base=Path(__file__).resolve().parents[1]
        workflow=(base / ".github/workflows/infra_analytics_experiment.yml").read_text()
        runner=(base / "infra/scripts/offline_batch_ci.sh").read_text()
        combined=workflow+"\\n"+runner
        self.assertIn("nivon-batch:worker", combined)
        self.assertIn("nivon-analytics:ci", combined)
        self.assertIn("nivon-analytics:distroless", combined)
        self.assertIn("infra_offline_pipeline", combined)
        for stage in ("prepare", "process", "reconcile", "verify", "backup", "restore"):
            self.assertIn(" " + stage, combined)
        for banned in ("docker push", "docker login", "secrets.", "continue-on-error: true"):
            self.assertNotIn(banned, combined)


if __name__ == "__main__":
    unittest.main()
