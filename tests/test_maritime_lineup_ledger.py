"""Synthetic E2E regression for SQLite line-up edition history, not production data."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.maritime.lineup_history import LineupVintage
from nivon.maritime.lineup_ledger import LineupVintageLedger
from nivon.maritime.maritime_store import MaritimeStore
from nivon.maritime.shipping_reconciliation import LineupCall


OLD_STAMP = "2026-10-20T10:00:00+00:00"
NEW_STAMP = "2026-10-20T15:00:00+00:00"


def vintage(*, port="SANTOS", source="APS", collected=OLD_STAMP,
            published="2026-10-20T09:30:00+00:00", digest="a" * 64,
            eta="2026-10-21T10:00:00+00:00", proof="published-proof",
            calls=None):
    if calls is None:
        calls = (LineupCall(
            call_id=port + ":" + source + ":DUV-001",
            port_id=port,
            source_id=source,
            vessel_name="SYNTHETIC MERCHANT",
            imo="9000001",
            eta=eta,
            collected_at=collected,
            planned_volume_t=15000.5,
            lineup_status="PROGRAMMED",
        ),)
    return LineupVintage(
        port_id=port, source_id=source, source_sha256=digest,
        collected_at=collected, reference_date="2026-10-20",
        competence="2026-10", published_at=published,
        publication_evidence_id=proof, calls=tuple(calls),
    )


def query(ledger, at="2026-10-20T12:00:00+00:00", *, port="SANTOS",
          source="APS", read_authorized=True):
    return ledger.select_asof(
        as_of=at, port_id=port, source_id=source, read_authorized=read_authorized,
    )


class LineupLedgerTests(unittest.TestCase):
    def test_deny_by_default_for_write_and_read(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            with self.assertRaises(PermissionError):
                ledger.save(vintage())
            with self.assertRaises(PermissionError):
                query(ledger, read_authorized=False)
            with self.assertRaises(PermissionError):
                ledger.count_editions(port_id="SANTOS", source_id="APS")

    def test_exact_snapshot_idempotence(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            self.assertTrue(ledger.save(vintage(), storage_authorized=True))
            self.assertFalse(ledger.save(vintage(), storage_authorized=True))
            self.assertEqual(ledger.count_editions(port_id="SANTOS", source_id="APS", read_authorized=True), 1)

    def test_conflicting_sha_same_instant_rejected_no_overwrite(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            ledger.save(vintage(), storage_authorized=True)
            with self.assertRaisesRegex(ValueError, "conflicting"):
                ledger.save(vintage(digest="b" * 64), storage_authorized=True)
            self.assertEqual(query(ledger).snapshot.source_sha256, "a" * 64)

    def test_conflicting_eta_same_sha_and_instant_rejected(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            ledger.save(vintage(), storage_authorized=True)
            with self.assertRaisesRegex(ValueError, "conflicting"):
                ledger.save(vintage(eta="2026-10-24T10:00:00+00:00"), storage_authorized=True)

    def test_asof_cannot_see_future_revision(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            ledger.save(vintage(), storage_authorized=True)
            ledger.save(vintage(collected=NEW_STAMP, published="2026-10-20T14:00:00+00:00",
                                digest="b" * 64, eta="2026-10-23T10:00:00+00:00"),
                        storage_authorized=True)
            self.assertEqual(query(ledger).snapshot.source_sha256, "a" * 64)
            self.assertEqual(query(ledger, at="2026-10-20T16:00:00+00:00").snapshot.source_sha256, "b" * 64)

    def test_published_but_collected_future_not_visible(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            ledger.save(vintage(collected=NEW_STAMP), storage_authorized=True)
            self.assertEqual(query(ledger).status, "DATA_GATED")
            self.assertIsNone(query(ledger).summary()["programmed_call_count"])

    def test_unknown_publication_can_be_stored_but_is_not_visible_asof(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            ledger.save(vintage(published=None, proof=None), storage_authorized=True)
            self.assertEqual(query(ledger, at="2026-10-25T16:00:00+00:00").status, "DATA_GATED")
            self.assertEqual(ledger.count_editions(port_id="SANTOS", source_id="APS", read_authorized=True), 1)

    def test_cross_port_and_cross_source_isolation(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            for item in (vintage(), vintage(port="PARANAGUA", source="PR"),
                         vintage(port="SANTOS", source="OTHER")):
                ledger.save(item, storage_authorized=True)
            self.assertEqual(query(ledger).snapshot.source_id, "APS")
            self.assertEqual(query(ledger, port="PARANAGUA", source="PR").snapshot.port_id, "PARANAGUA")
            self.assertEqual(query(ledger, source="NOT_FOUND").status, "DATA_GATED")

    def test_zero_programmed_rows_not_zero_real_operations(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            ledger.save(vintage(calls=()), storage_authorized=True)
            result = query(ledger).summary()
            self.assertEqual(result["programmed_call_count"], 0)
            self.assertIsNone(result["operated_call_count"])
            self.assertIsNone(result["realized_volume_t"])
            self.assertFalse(result["publication_allowed"])

    def test_same_imo_distinct_duvs_preserved(self):
        call1 = vintage().calls[0]
        call2 = LineupCall(
            call_id="SANTOS:APS:DUV-002", port_id="SANTOS", source_id="APS",
            vessel_name=call1.vessel_name, imo=call1.imo,
            eta=call1.eta, collected_at=OLD_STAMP,
        )
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            ledger.save(vintage(calls=(call1, call2)), storage_authorized=True)
            result = query(ledger)
            self.assertEqual(len(result.programmed_calls), 2)

    def test_naive_cutoff_and_invalid_arguments_rejected(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            with self.assertRaisesRegex(ValueError, "timezone"):
                query(ledger, at="2026-10-20T12:00:00")
            with self.assertRaises(ValueError):
                query(ledger, port="")
            with self.assertRaises(ValueError):
                ledger.count_editions(port_id="", source_id="APS", read_authorized=True)

    def test_persistent_file_reopen_and_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "maritime.sqlite"
            with MaritimeStore(path) as store:
                ledger = LineupVintageLedger(store)
                ledger.save(vintage(), storage_authorized=True)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with MaritimeStore(path) as store:
                ledger = LineupVintageLedger(store)
                self.assertEqual(query(ledger).snapshot.source_sha256, "a" * 64)

    def test_backup_and_restore_query_persisted_asof(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "maritime.sqlite"
            backup = Path(folder) / "backup.sqlite"
            with MaritimeStore(path) as store:
                ledger = LineupVintageLedger(store)
                ledger.save(vintage(), storage_authorized=True)
                ledger.save(vintage(collected=NEW_STAMP,
                                    published="2026-10-20T14:00:00+00:00",
                                    digest="b" * 64), storage_authorized=True)
                receipt = store.backup(backup, backup_authorized=True)
                self.assertEqual(receipt["integrity"], "ok")
            validation = MaritimeStore.validate_restore(backup)
            self.assertEqual(validation["integrity"], "ok")
            self.assertEqual(validation["lineup_vintage_rows"], 2)
            with MaritimeStore(backup) as store:
                ledger = LineupVintageLedger(store)
                self.assertEqual(ledger.count_editions(port_id="SANTOS", source_id="APS", read_authorized=True), 2)
                self.assertEqual(query(ledger).snapshot.source_sha256, "a" * 64)

    def test_metadata_corruption_blocks_read(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            ledger.save(vintage(), storage_authorized=True)
            store.db.execute("UPDATE maritime_lineup_vintages SET source_sha256=?", ("b" * 64,))
            store.db.commit()
            with self.assertRaisesRegex(ValueError, "metadata mismatch"):
                query(ledger)

    def test_payload_corruption_blocks_read(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            ledger.save(vintage(), storage_authorized=True)
            store.db.execute("UPDATE maritime_lineup_vintages SET payload_json='{}'")
            store.db.commit()
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                query(ledger)

    def test_second_connection_conflict_not_silent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "maritime.sqlite"
            with MaritimeStore(path) as first, MaritimeStore(path) as second:
                a, b = LineupVintageLedger(first), LineupVintageLedger(second)
                a.save(vintage(), storage_authorized=True)
                with self.assertRaisesRegex(ValueError, "conflicting"):
                    b.save(vintage(digest="c" * 64), storage_authorized=True)
                self.assertFalse(b.save(vintage(), storage_authorized=True))

    def test_source_and_edition_not_exposed_without_rights(self):
        with MaritimeStore() as store:
            ledger = LineupVintageLedger(store)
            ledger.save(vintage(), storage_authorized=True)
            with self.assertRaises(PermissionError):
                ledger.select_asof(port_id="SANTOS", source_id="APS",
                                   as_of="2026-10-20T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
