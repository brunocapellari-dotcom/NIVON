"""Native pg_dump PTAX: all tests use synthetic archive doubles, never Neon."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "ptax_postgres_native_backup.py"
spec = importlib.util.spec_from_file_location("nivon_pg_native", MODULE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def pg_toc(*, missing=None):
    entries = [
        (m.TABLES[0], "TABLE"),
        (m.TABLES[1], "TABLE"),
        (m.TABLES[2], "TABLE"),
        (m.TABLES[0], "TABLE DATA"),
        (m.TABLES[1], "TABLE DATA"),
        (m.TABLES[2], "TABLE DATA"),
        (m.SEQUENCES[0], "SEQUENCE SET"),
        (m.SEQUENCES[1], "SEQUENCE SET"),
    ]
    return "\n".join(
        f"{100+i}; 1259 {1000+i} {category} public {name} nivonowner"
        for i, (name, category) in enumerate(entries)
        if (name, category) != missing
    )


class NativeBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "backup"
        self.calls = []
        self.env = {"PGSERVICE": "nivon-private", "HOME": self.temp.name}

    def run_cli(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd[0] == "pg_dump":
            loc = next(c for c in cmd if c.startswith("--file=")).split("=", 1)[1]
            Path(loc).write_bytes(b"PGDMP" + b"synthetic-not-a-real-pg-dump" * 90)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "pg_restore":
            return subprocess.CompletedProcess(cmd, 0, pg_toc(), "")
        raise AssertionError("unexpected subprocess call")

    def test_build_then_verify_secure_archive(self):
        one = m.build(self.folder, runner=self.run_cli, env=self.env)
        two = m.verify(self.folder, runner=self.run_cli)
        self.assertEqual(one, two)
        self.assertEqual(one["status"], "LOCAL_PGDUMP_ARCHIVE_TOC_VERIFIED")
        self.assertEqual(set(one["tables_confirmed"]), set(m.TABLES))
        self.assertEqual(len(one["archive_sha256"]), 64)
        self.assertFalse(one["native_postgres_restore_verified"])
        self.assertFalse(one["bigquery_cutover_approved"])
        self.assertFalse(one["stored_offsite"])
        self.assertEqual(len(self.calls), 3)
        dump_cmd = self.calls[0][0]
        self.assertIn("--serializable-deferrable", dump_cmd)
        self.assertIn("--no-password", dump_cmd)
        self.assertIn("--dbname=nivon", dump_cmd)
        self.assertIn("--format=custom", dump_cmd)
        self.assertEqual(
            len([v for v in dump_cmd if v.startswith("--table=")]),
            len(m.TABLES) + len(m.SEQUENCES),
        )
        self.assertNotIn("--clean", dump_cmd)
        self.assertNotIn("--create", dump_cmd)
        self.assertFalse(any(v.startswith("--password") for v in dump_cmd))
        if os.name != "nt":
            self.assertEqual(self.folder.stat().st_mode & 0o777, 0o700)
            self.assertEqual((self.folder / m.BACKUP_NAME).stat().st_mode & 0o777, 0o600)
            self.assertEqual((self.folder / m.MANIFEST_NAME).stat().st_mode & 0o777, 0o600)

    def test_no_pgservice_never_starts_dump(self):
        with self.assertRaises(m.BackupBlocked):
            m.build(self.folder, runner=self.run_cli, env={"HOME":self.temp.name})
        self.assertFalse(self.folder.exists())
        self.assertEqual(self.calls, [])

    def test_password_in_env_blocked(self):
        with self.assertRaises(m.BackupBlocked):
            m.build(self.folder, runner=self.run_cli,
                    env={**self.env, "PGPASSWORD":"secret-should-not-leak"})
        self.assertEqual(self.calls, [])
        self.assertFalse(self.folder.exists())

    def test_missing_home_and_pgservicefile_blocked(self):
        with self.assertRaises(m.BackupBlocked):
            m.build(self.folder, runner=self.run_cli, env={"PGSERVICE":"n"})
        self.assertEqual(self.calls, [])

    def test_destination_exists_blocked(self):
        self.folder.mkdir()
        with self.assertRaises(m.BackupBlocked):
            m.build(self.folder, runner=self.run_cli, env=self.env)
        self.assertEqual(self.calls, [])

    def test_root_checkout_path_blocked(self):
        with self.assertRaises(m.BackupBlocked):
            m.build(ROOT / "archive-never-create", runner=self.run_cli, env=self.env)
        self.assertEqual(self.calls, [])

    def test_dump_error_redacted_and_cleaned(self):
        def fail(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, "", "password-protected")
        with self.assertRaises(m.BackupBlocked) as err:
            m.build(self.folder, runner=fail, env=self.env)
        self.assertNotIn("password-protected", str(err.exception))
        self.assertFalse(self.folder.exists())

    def test_missing_archive_blocks_and_cleans(self):
        def fake(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with self.assertRaises(m.BackupBlocked):
            m.build(self.folder, runner=fake, env=self.env)
        self.assertFalse(self.folder.exists())

    def test_missing_sequence_value_blocks_and_cleans(self):
        def fake(cmd, **kw):
            if cmd[0] == "pg_dump":
                return self.run_cli(cmd, **kw)
            return subprocess.CompletedProcess(
                cmd, 0, pg_toc(missing=(m.SEQUENCES[0], "SEQUENCE SET")), ""
            )
        with self.assertRaises(m.BackupBlocked):
            m.build(self.folder, runner=fake, env=self.env)
        self.assertFalse(self.folder.exists())

    def test_missing_table_data_blocks_and_cleans(self):
        def fake(cmd, **kw):
            if cmd[0] == "pg_dump":
                return self.run_cli(cmd, **kw)
            return subprocess.CompletedProcess(
                cmd, 0, pg_toc(missing=(m.TABLES[1], "TABLE DATA")), ""
            )
        with self.assertRaises(m.BackupBlocked):
            m.build(self.folder, runner=fake, env=self.env)
        self.assertFalse(self.folder.exists())

    def test_damaged_archive_detected(self):
        m.build(self.folder, runner=self.run_cli, env=self.env)
        p = self.folder / m.BACKUP_NAME
        p.write_bytes(p.read_bytes() + b"tamper")
        with self.assertRaises(m.BackupBlocked):
            m.verify(self.folder, runner=self.run_cli)

    def test_manifest_false_claim_detection(self):
        m.build(self.folder, runner=self.run_cli, env=self.env)
        p = self.folder / m.MANIFEST_NAME
        obj = json.loads(p.read_text(encoding="utf-8"))
        obj["native_postgres_restore_verified"] = True
        p.write_text(json.dumps(obj))
        with self.assertRaises(m.BackupBlocked):
            m.verify(self.folder, runner=self.run_cli)

    def test_symlinked_archive_blocked(self):
        m.build(self.folder, runner=self.run_cli, env=self.env)
        p = self.folder / m.BACKUP_NAME
        external = Path(self.temp.name) / "external.pgcustom"
        p.rename(external)
        p.symlink_to(external)
        with self.assertRaises(m.BackupBlocked):
            m.verify(self.folder, runner=self.run_cli)

    def test_new_file_in_package_rejected(self):
        m.build(self.folder, runner=self.run_cli, env=self.env)
        (self.folder / "unexpected").write_text("x")
        with self.assertRaises(m.BackupBlocked):
            m.verify(self.folder, runner=self.run_cli)

    def test_restore_command_only_reads_archive(self):
        m.build(self.folder, runner=self.run_cli, env=self.env)
        pg_restore = [args for args, _ in self.calls if args[0] == "pg_restore"]
        self.assertTrue(pg_restore)
        for args in pg_restore:
            self.assertEqual(args[:2], ["pg_restore", "--list"])
            self.assertNotIn("--dbname", " ".join(args))
            self.assertNotIn("--clean", args)

    def test_no_args_do_not_run_pg(self):
        with mock.patch.object(m, "build", side_effect=AssertionError("unexpected pg_dump")):
            with self.assertRaises(SystemExit):
                m.main([])

    def test_forged_small_archive_rejected(self):
        def fake(cmd, **kw):
            if cmd[0] == "pg_dump":
                p = Path(next(a for a in cmd if a.startswith("--file=")).split("=", 1)[1])
                p.write_bytes(b"123")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, pg_toc(), "")
        with self.assertRaises(m.BackupBlocked):
            m.build(self.folder, runner=fake, env=self.env)
        self.assertFalse(self.folder.exists())


if __name__ == "__main__":
    unittest.main()
