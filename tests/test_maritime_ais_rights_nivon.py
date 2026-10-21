"""AISStream provider must never stream based solely on presence of an API key."""
import unittest
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from nivon.maritime.ais_stream_client import (
    AISStreamRights, _validate_stream_url, stream_once, run_forever,
)


def rights(**options):
    args = dict(
        evidence_id="SIGNED_SOURCE_RIGHTS_REF",
        granted_by="UPSTREAM_DATA_PROVIDER",
        collected_permission=True,
        commercial_display_permission=False,
        storage_permission=False,
        expires_at=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat(),
    )
    args.update(options)
    return AISStreamRights(**args)


class TestAISStreamRights(unittest.TestCase):
    def test_absent_rights_blocks_before_import_or_network(self):
        with self.assertRaises(PermissionError):
            next(stream_once(api_key="placeholder", bounding_boxes=[]))
        with self.assertRaises(PermissionError):
            run_forever(api_key="placeholder", bounding_boxes=[], on_record=lambda _: None,
                        stop_after_records=1)

    def test_collection_must_be_granted(self):
        with self.assertRaises(PermissionError):
            rights(collected_permission=False).validate("COLLECT")
        with self.assertRaises(PermissionError):
            next(stream_once(api_key="placeholder", bounding_boxes=[],
                             rights=rights(collected_permission=False)))

    def test_expired_or_naive_rights_rejected(self):
        with self.assertRaises(PermissionError):
            rights(expires_at="2025-01-01T00:00:00Z").validate("COLLECT")
        with self.assertRaises(PermissionError):
            rights(expires_at="2030-01-01T00:00:00").validate("COLLECT")

    def test_independent_permission_for_storage_and_commercial(self):
        permit = rights()
        permit.validate("COLLECT")
        with self.assertRaises(PermissionError):
            permit.validate("STORE")
        with self.assertRaises(PermissionError):
            permit.validate("DISPLAY_COMMERCIAL")
        allowed = rights(storage_permission=True,commercial_display_permission=True)
        allowed.validate("STORE")
        allowed.validate("DISPLAY_COMMERCIAL")

    def test_missing_documentary_provenance_rejected(self):
        with self.assertRaises(PermissionError):
            rights(evidence_id="").validate("COLLECT")
        with self.assertRaises(PermissionError):
            rights(granted_by=" ").validate("COLLECT")

    def test_url_must_be_exact_official_endpoint(self):
        _validate_stream_url("wss://stream.aisstream.io/v0/stream")
        for invalid in (
            "ws://stream.aisstream.io/v0/stream",
            "wss://evil.example/v0/stream",
            "wss://stream.aisstream.io/v1/stream",
            "wss://stream.aisstream.io/v0/stream?redirect=1",
            "wss://user@stream.aisstream.io/v0/stream",
            "wss://stream.aisstream.io:8443/v0/stream",
        ):
            with self.assertRaises(ValueError, msg=invalid):
                _validate_stream_url(invalid)

    def test_unknown_operation_denied(self):
        with self.assertRaises(ValueError):
            rights().validate("EXPORT")

    def test_expiry_current_time_is_not_accepted(self):
        at = datetime(2026, 10, 20, tzinfo=timezone.utc)
        p = rights(expires_at=at.isoformat())
        with self.assertRaises(PermissionError):
            p.validate("COLLECT", now=at)


if __name__ == "__main__":
    unittest.main()
