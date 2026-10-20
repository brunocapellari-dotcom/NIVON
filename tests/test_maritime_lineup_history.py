"""Strict as-of/snapshot revision regressions with wholly synthetic line-ups."""
import unittest

from nivon.maritime.lineup_history import (
    LineupVintage, compare_lineup_vintages, select_lineup_asof,
)
from nivon.maritime.shipping_reconciliation import LineupCall


def call(
    call_id="SANTOS:APS:DUV-001", *,
    collection="2026-10-20T10:00:00+00:00",
    eta="2026-10-21T12:00:00+00:00",
    port="SANTOS",
    source="APS",
    volume=65000.0,
    imo="9000001",
    status="PROGRAMMED",
):
    return LineupCall(
        call_id=call_id,
        port_id=port,
        source_id=source,
        vessel_name="SYNTHETIC STAR",
        imo=imo,
        eta=eta,
        collected_at=collection,
        planned_volume_t=volume,
        lineup_status=status,
    )


def vintage(*, stamp="2026-10-20T10:00:00+00:00", published="2026-10-20T09:00:00+00:00",
            proof="synthetic-publication-proof", digest="a" * 64, port="SANTOS",
            source="APS", calls=None, **extra):
    return LineupVintage(
        port_id=port,
        source_id=source,
        source_sha256=digest,
        collected_at=stamp,
        reference_date="2026-10-20",
        competence="2026-10",
        published_at=published,
        publication_evidence_id=proof,
        calls=tuple(calls if calls is not None else [call(collection=stamp, port=port, source=source)]),
        **extra,
    )


def select(rows, at="2026-10-20T12:00:00+00:00", port="SANTOS", source="APS"):
    return select_lineup_asof(rows, as_of=at, port_id=port, source_id=source)


class LineupHistoryTests(unittest.TestCase):
    def test_four_dates_and_sha_are_preserved(self):
        fields = vintage().provenance()
        self.assertEqual(fields["competencia"], "2026-10")
        self.assertEqual(fields["data_referencia"], "2026-10-20")
        self.assertEqual(fields["data_publicacao"], "2026-10-20T09:00:00+00:00")
        self.assertEqual(fields["data_coleta"], "2026-10-20T10:00:00+00:00")
        self.assertEqual(fields["source_sha256"], "a" * 64)

    def test_select_only_currently_known_snapshot_not_latest_revision(self):
        old = vintage()
        new = vintage(stamp="2026-10-20T15:00:00+00:00",
                      published="2026-10-20T14:00:00+00:00", digest="b" * 64,
                      calls=[call(collection="2026-10-20T15:00:00+00:00",
                                  eta="2026-10-23T13:00:00+00:00")])
        result = select([new, old])
        self.assertIs(result.snapshot, old)
        self.assertEqual(result.programmed_calls[0].eta_utc.isoformat(), "2026-10-21T12:00:00+00:00")
        later = select([new, old], at="2026-10-20T16:00:00+00:00")
        self.assertIs(later.snapshot, new)

    def test_published_before_cutoff_but_collected_later_cannot_leak(self):
        row = vintage(stamp="2026-10-20T15:00:00+00:00",
                      published="2026-10-20T09:00:00+00:00",
                      calls=[call(collection="2026-10-20T15:00:00+00:00")])
        result = select([row])
        self.assertEqual(result.status, "DATA_GATED")
        self.assertIsNone(result.programmed_calls)
        self.assertIsNone(result.summary()["programmed_call_count"])

    def test_publication_unknown_never_enters_asof(self):
        row = vintage(published=None, proof=None)
        self.assertEqual(select([row]).status, "DATA_GATED")

    def test_present_empty_snapshot_distinct_from_unknown(self):
        result = select([vintage(calls=[])])
        self.assertEqual(result.status, "PROGRAMMED_SNAPSHOT_ONLY")
        self.assertEqual(result.programmed_calls, ())
        self.assertEqual(result.summary()["programmed_call_count"], 0)
        self.assertIsNone(result.summary()["operated_call_count"])
        self.assertIsNone(result.summary()["realized_volume_t"])

    def test_future_eta_is_legal_schedule_and_not_an_observed_arrival(self):
        result = select([vintage()])
        self.assertGreater(result.programmed_calls[0].eta_utc.isoformat(), result.as_of)
        self.assertFalse(result.summary()["publication_allowed"])

    def test_other_port_and_source_are_not_mixed(self):
        row1 = vintage()
        row2 = vintage(port="PARANAGUA", source="PORTOS_PR")
        self.assertIs(select([row1, row2]).snapshot, row1)
        self.assertIs(select([row1, row2], port="PARANAGUA", source="PORTOS_PR").snapshot, row2)

    def test_same_imo_multiple_duvs_remain_two_calls(self):
        row = vintage(calls=[
            call(call_id="SANTOS:APS:DUV-001", imo="9000001"),
            call(call_id="SANTOS:APS:DUV-002", imo="9000001"),
        ])
        self.assertEqual(select([row]).summary()["programmed_call_count"], 2)

    def test_duplicate_call_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            vintage(calls=[call(), call()])

    def test_mixed_source_or_port_rejected(self):
        for row in (call(port="PARANAGUA"), call(source="OTHER")):
            with self.subTest(row=row):
                with self.assertRaisesRegex(ValueError, "another"):
                    vintage(calls=[row])

    def test_publication_after_collection_rejected(self):
        with self.assertRaisesRegex(ValueError, "after collection"):
            vintage(published="2026-10-21T12:00:00+00:00")

    def test_publication_evidence_required_in_both_directions(self):
        with self.assertRaises(ValueError):
            vintage(published=None, proof="evidence")
        with self.assertRaises(ValueError):
            vintage(published="2026-10-20T09:00:00+00:00", proof=None)

    def test_naive_datetime_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            vintage(stamp="2026-10-20T10:00:00")
        with self.assertRaisesRegex(ValueError, "timezone"):
            select([vintage()], at="2026-10-20T12:00:00")

    def test_different_collection_in_call_rejected(self):
        with self.assertRaisesRegex(ValueError, "another collection"):
            vintage(calls=[call(collection="2026-10-20T09:00:00+00:00")])

    def test_nonfinite_and_negative_volumes_rejected(self):
        for volume in (float("nan"), float("inf"), -1.0):
            with self.subTest(volume=volume):
                with self.assertRaisesRegex(ValueError, "invalid planned"):
                    vintage(calls=[call(volume=volume)])

    def test_same_collection_conflicting_hash_must_not_autopick(self):
        with self.assertRaisesRegex(ValueError, "conflicting"):
            select([vintage(), vintage(digest="b" * 64)])

    def test_hash_idempotent_metadata_conflict_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "contradictory metadata"):
            select([vintage(), vintage(proof="different-publication-evidence")])

    def test_changing_eta_and_declared_status_never_proves_realization(self):
        old = vintage()
        new = vintage(stamp="2026-10-20T16:00:00+00:00",
                      published="2026-10-20T15:00:00+00:00", digest="b" * 64,
                      calls=[call(collection="2026-10-20T16:00:00+00:00",
                                  eta="2026-10-22T12:00:00+00:00", status="COMPLETED")])
        changes = compare_lineup_vintages(old, new)
        self.assertIn("eta", [c.field for c in changes])
        self.assertIn("lineup_status_declared", [c.field for c in changes])
        self.assertTrue(all(c.classification == "LINEUP_REVISION_NOT_CONFIRMED_OPERATION" for c in changes))

    def test_disappearance_is_not_assumed_departed(self):
        old = vintage()
        new = vintage(stamp="2026-10-20T16:00:00+00:00",
                      published="2026-10-20T15:00:00+00:00", digest="b" * 64, calls=[])
        changes = compare_lineup_vintages(old, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].field, "absent_from_new_snapshot_unconfirmed")
        self.assertIsNone(changes[0].after)

    def test_cross_port_revision_not_allowed(self):
        with self.assertRaisesRegex(ValueError, "source and port"):
            compare_lineup_vintages(vintage(), vintage(port="PARANAGUA", source="PORTOS_PR"))

    def test_backwards_revision_not_allowed(self):
        with self.assertRaisesRegex(ValueError, "collected later"):
            compare_lineup_vintages(vintage(), vintage())


if __name__ == "__main__":
    unittest.main()
