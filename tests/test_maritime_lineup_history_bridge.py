"""Synthetic contract tests for converting official HTML bridge evidence into vintages."""
import unittest
from dataclasses import replace

from nivon.maritime.lineup_history import select_lineup_asof, vintage_from_official_bridge
from nivon.maritime.official_lineup_bridge import LineupBridgeResult
from nivon.maritime.shipping_reconciliation import LineupCall


STAMP = "2026-10-20T10:00:00+00:00"


def result(**kwargs):
    candidates = (LineupCall(
        call_id="SANTOS:APS:DUV001", port_id="SANTOS", source_id="APS",
        vessel_name="SYNTHETIC VESSEL", eta="2026-10-21T10:00:00+00:00",
        collected_at=STAMP, planned_volume_t=20000.0,
    ),)
    fields = dict(
        port_id="SANTOS", source_id="APS",
        source_url="https://www.portodesantos.com.br/",
        document_sha256="b" * 64, collected_at=STAMP, candidates=candidates,
        excluded=(), source_rows=1,
    )
    fields.update(kwargs)
    return LineupBridgeResult(**fields)


def adapt(bridge=None, **kwargs):
    args = dict(reference_date="2026-10-20", competence="2026-10",
                published_at="2026-10-20T09:30:00+00:00",
                publication_evidence_id="synthetic-official-pub-proof")
    args.update(kwargs)
    return vintage_from_official_bridge(bridge if bridge is not None else result(), **args)


class BridgeHistoryTests(unittest.TestCase):
    def test_complete_bridge_keeps_sha_and_programming(self):
        vintage = adapt()
        self.assertEqual(vintage.source_sha256, "b" * 64)
        self.assertEqual(vintage.calls[0].call_id, "SANTOS:APS:DUV001")
        asof = select_lineup_asof([vintage], as_of="2026-10-20T11:00:00+00:00",
                                 port_id="SANTOS", source_id="APS")
        self.assertEqual(asof.status, "PROGRAMMED_SNAPSHOT_ONLY")
        self.assertIsNone(asof.summary()["realized_volume_t"])
        self.assertFalse(asof.summary()["publication_allowed"])

    def test_document_without_proven_publication_is_not_asof_eligible(self):
        vintage = adapt(published_at=None, publication_evidence_id=None)
        asof = select_lineup_asof([vintage], as_of="2026-10-20T11:00:00+00:00",
                                 port_id="SANTOS", source_id="APS")
        self.assertEqual(asof.status, "DATA_GATED")

    def test_excluded_rows_cannot_masquerade_as_complete_schedule(self):
        incomplete = result(source_rows=2, excluded=({"row": "2", "reason": "duv_missing"},))
        with self.assertRaisesRegex(ValueError, "partial lineup"):
            adapt(incomplete)

    def test_missing_source_rows_blocked(self):
        incomplete = result(source_rows=2)
        with self.assertRaisesRegex(ValueError, "partial lineup"):
            adapt(incomplete)

    def test_empty_parse_does_not_prove_no_scheduled_vessels(self):
        empty = result(source_rows=0, candidates=())
        with self.assertRaisesRegex(ValueError, "not proof"):
            adapt(empty)

    def test_realized_cargo_claim_forbidden(self):
        with self.assertRaisesRegex(ValueError, "realized cargo"):
            adapt(result(realized_cargo_claimed=True))

    def test_release_claim_forbidden(self):
        with self.assertRaisesRegex(ValueError, "publication"):
            adapt(result(publication_allowed=True))

    def test_unexpected_bridge_state_not_promoted(self):
        with self.assertRaisesRegex(ValueError, "lifecycle"):
            adapt(result(state="PUBLISHED"))

    def test_unknown_bridge_type_rejected(self):
        with self.assertRaises(TypeError):
            adapt(bridge={"port_id": "SANTOS"})


if __name__ == "__main__":
    unittest.main()
