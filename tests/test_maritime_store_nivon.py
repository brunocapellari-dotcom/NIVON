"""Regressoes SQLite de arquivo bruto AIS e lineup; nenhuma rede ou segredo."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.maritime.maritime_store import MaritimeStore

NOW = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)


class TestMaritimeStore(unittest.TestCase):
    @staticmethod
    def row():
        return {
            "mmsi": "123456789", "observed_at": NOW.isoformat(),
            "latitude": -13.0, "longitude": -56.0,
            "message_type": "PositionReport",
        }

    def test_deny_by_default(self):
        with MaritimeStore() as store:
            with self.assertRaises(PermissionError):
                store.save_ais(self.row(), source_id="FIXTURE", collected_at=NOW)
            with self.assertRaises(PermissionError):
                store.save_lineup({"vessel": "X"}, source_id="FIXTURE",
                                  port_id="PORTO_TESTE", collected_at=NOW)
            self.assertEqual(store.replay(
                port_id="PORTO_TESTE", start=NOW, end=NOW,
            ), [])

    def test_idempotent_ais_and_replay(self):
        with MaritimeStore() as store:
            self.assertTrue(store.save_ais(
                self.row(), source_id="FIXTURE", collected_at=NOW,
                storage_authorized=True, port_id="PORTO_TESTE",
            ))
            self.assertFalse(store.save_ais(
                self.row(), source_id="FIXTURE", collected_at=NOW,
                storage_authorized=True, port_id="PORTO_TESTE",
            ))
            replay = store.replay(
                port_id="PORTO_TESTE", start=NOW-timedelta(days=1), end=NOW,
            )
            self.assertEqual(len(replay), 1)
            self.assertEqual(replay[0]["quality_status"], "UNVALIDATED")

    def test_never_mix_different_ports(self):
        with MaritimeStore() as store:
            store.save_ais(self.row(), source_id="FIXTURE", collected_at=NOW,
                           storage_authorized=True, port_id="SANTAREM")
            self.assertEqual(store.replay(
                port_id="PARANAGUA", start=NOW, end=NOW,
            ), [])

    def test_reject_naive_timestamps(self):
        with MaritimeStore() as store:
            with self.assertRaises(ValueError):
                store.save_ais(self.row(), source_id="FIXTURE",
                               collected_at="2026-10-19T15:00:00",
                               storage_authorized=True)

    def test_invalid_replay_window(self):
        with MaritimeStore() as store:
            with self.assertRaises(ValueError):
                store.replay(port_id="SANTOS", start=NOW, end=NOW-timedelta(hours=1))
            with self.assertRaises(ValueError):
                store.replay(port_id="SANTOS", start=NOW, end=NOW, limit=5001)

    def test_backup_restore_has_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            backup = Path(folder) / "maritime.bak.sqlite"
            with MaritimeStore() as store:
                store.save_ais(self.row(), source_id="FIXTURE", collected_at=NOW,
                               storage_authorized=True, port_id="PORTO_TESTE")
                store.save_lineup({"vessel": "NAVIO SIMULADO"}, source_id="PORTO_TESTE",
                                  port_id="PORTO_TESTE", collected_at=NOW,
                                  storage_authorized=True)
                with self.assertRaises(PermissionError):
                    store.backup(backup)
                evidence = store.backup(backup, backup_authorized=True)
                self.assertEqual(evidence["integrity"], "ok")
            restoration = MaritimeStore.validate_restore(backup)
            self.assertEqual(restoration["ais_rows"], 1)
            self.assertEqual(restoration["lineup_rows"], 1)
            self.assertEqual(restoration["integrity"], "ok")

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "real.sqlite"
            target.write_bytes(b"test")
            alias = Path(folder) / "alias.sqlite"
            alias.symlink_to(target)
            with self.assertRaises(ValueError):
                MaritimeStore(alias)


if __name__ == "__main__":
    unittest.main()
