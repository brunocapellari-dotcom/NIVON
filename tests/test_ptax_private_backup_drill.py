"""Testes offline do backup portátil PTAX; usam apenas fixtures inventadas."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ptax_private_backup_drill as bk


def quote(**v):
    x = {
        "id": 1, "currency": "USD", "reference_date": "2026-10-21",
        "quote_time_original": "2026-10-21 13:03:07",
        "bulletin_type": "COTACAO_DOLAR_DIARIA",
        "buy_brl": "5.123456789", "sell_brl": "5.123456790", "unit": "BRL/USD",
        "source": "Banco Central do Brasil / PTAX", "license": "ODbL",
        "published_at": None,
        "first_collected_at": "2026-10-21T10:10:00-04:00",
        "last_verified_at": "2026-10-21T11:10:00-04:00",
        "observation_kind": "INFORMADO",
    }
    x.update(v)
    return x


def run(**v):
    x = {
        "id": 1, "job_type": "BACKFILL", "currency": "USD",
        "window_start": "2020-01-01", "window_end": "2020-01-31",
        "started_at": "2026-10-21T11:10:00Z", "finished_at": "2026-10-21T11:11:00Z",
        "status": "SUCCESS", "fetched": 22, "inserted": 22, "error_class": None,
        "detail": None,
    }
    x.update(v)
    return x


def checkpoint(**v):
    x = {
        "currency": "USD", "window_start": "2020-01-01",
        "window_end": "2020-01-31", "last_completed_at": "2026-10-21T11:11:00Z",
        "status": "SUCCESS", "fetched": 22,
    }
    x.update(v)
    return x


class BackupDrillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "private-exports"
        self.source.mkdir()
        self.bundle = self.root / "backup-package"
        self.make_exports()

    def make_exports(self, quotes=None, runs=None, checkpoints=None):
        data = {
            "quotes": [quote()] if quotes is None else quotes,
            "runs": [run()] if runs is None else runs,
            "checkpoints": [checkpoint()] if checkpoints is None else checkpoints,
        }
        for kind, name in bk.FILES.items():
            (self.source / name).write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in data[kind]),
                encoding="utf-8",
            )

    def test_build_and_verify_roundtrip(self):
        first = bk.build(self.source, self.bundle)
        second = bk.verify(self.bundle)
        self.assertEqual(first, second)
        self.assertEqual(first["table_counts"], {"quotes": 1, "runs": 1, "checkpoints": 1})
        self.assertTrue(first["sqlite_memory_replay_verified"])
        for gate in ("snapshot_consistency_verified", "origin_neon_reconciled",
                     "independent_storage_verified", "postgres_native_restore_verified",
                     "cloud_migration_completed", "cutover_allowed"):
            self.assertFalse(first[gate])
        self.assertNotIn("5.123456789", str(first))
        self.assertEqual(len(first["archive_sha256"]), 64)

    def test_private_file_permissions(self):
        bk.build(self.source, self.bundle)
        if os.name != "nt":
            self.assertEqual(self.bundle.stat().st_mode & 0o777, 0o700)
            for file in self.bundle.iterdir():
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_does_not_overwrite(self):
        bk.build(self.source, self.bundle)
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, self.bundle)

    def test_source_never_deleted(self):
        before = (self.source / bk.FILES["quotes"]).read_bytes()
        bk.build(self.source, self.bundle)
        self.assertEqual((self.source / bk.FILES["quotes"]).read_bytes(), before)

    def test_source_no_quotes_cannot_be_success(self):
        self.make_exports(quotes=[])
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, self.bundle)
        self.assertFalse(self.bundle.exists())

    def test_invalid_line_never_creates_bundle(self):
        self.make_exports(quotes=[quote(), quote(currency="GBP")])
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, self.bundle)
        self.assertFalse(self.bundle.exists())

    def test_business_duplicate_rejected(self):
        self.make_exports(quotes=[quote(), quote(id=2)])
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, self.bundle)

    def test_run_duplicate_rejected(self):
        self.make_exports(runs=[run(), run()])
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, self.bundle)

    def test_checkpoint_duplicate_rejected(self):
        self.make_exports(checkpoints=[checkpoint(), checkpoint()])
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, self.bundle)

    def test_wrong_run_job_status_rejected(self):
        self.make_exports(runs=[run(status="DONE")])
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, self.bundle)

    def test_invalid_run_window_rejected(self):
        self.make_exports(runs=[run(window_end="2019-12-31")])
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, self.bundle)

    def test_invalid_checkpoint_fetched_rejected(self):
        self.make_exports(checkpoints=[checkpoint(fetched=-1)])
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, self.bundle)

    def test_tampered_data_detected(self):
        bk.build(self.source, self.bundle)
        target = self.bundle / bk.FILES["quotes"]
        target.write_bytes(target.read_bytes().replace(b"5.123456789", b"5.123456788"))
        with self.assertRaises(bk.BackupError):
            bk.verify(self.bundle)

    def test_modified_manifest_not_allowed_to_claim_restore(self):
        bk.build(self.source, self.bundle)
        file = self.bundle / "manifest.json"
        obj = json.loads(file.read_text())
        obj["postgres_native_restore_verified"] = True
        file.write_text(json.dumps(obj))
        with self.assertRaises(bk.BackupError):
            bk.verify(self.bundle)

    def test_extra_file_rejected(self):
        bk.build(self.source, self.bundle)
        (self.bundle / "unknown.txt").write_text("hello")
        with self.assertRaises(bk.BackupError):
            bk.verify(self.bundle)

    def test_symlinked_data_rejected(self):
        bk.build(self.source, self.bundle)
        dest = self.bundle / bk.FILES["runs"]
        dest.unlink()
        dest.symlink_to(self.source / bk.FILES["runs"])
        with self.assertRaises(bk.BackupError):
            bk.verify(self.bundle)

    def test_public_repository_path_rejected(self):
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, ROOT / "not-created-private-archive")

    def test_same_root_as_source_rejected(self):
        with self.assertRaises(bk.BackupError):
            bk.build(self.source, self.source / "nested")

    def test_cli_requires_mode_without_network(self):
        with mock.patch("sys.stdout"):
            with self.assertRaises(SystemExit):
                bk.main(["--bundle", str(self.bundle)])

    def test_cli_build_then_verify(self):
        with mock.patch("sys.stdout"):
            self.assertEqual(bk.main(["--build", "--source", str(self.source),
                                      "--bundle", str(self.bundle)]), 0)
            self.assertEqual(bk.main(["--verify", "--bundle", str(self.bundle)]), 0)


if __name__ == "__main__":
    unittest.main()
