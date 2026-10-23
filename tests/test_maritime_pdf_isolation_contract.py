"""No-dependency fail-closed tests for isolated PDF worker protocol."""
from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from nivon.maritime.isolated_pdf_extract import extract_pdf_tables_isolated

FAKE_PDF = b"%PDF-1.4\nSYNTHETIC-NO-REAL-AUTHORITY"


def completed(*, digest=None, tables=None, returncode=0, payload=None):
    if payload is None:
        payload = {
            "schema_version": 1,
            "source_sha256": digest or hashlib.sha256(FAKE_PDF).hexdigest(),
            "tables": tables or [
                {"page_number": 1, "rows": [["Navio", "DUV"], ["FICTICIO", "DUV-TEST"]]}
            ],
        }
    return SimpleNamespace(
        returncode=returncode,
        stdout=json.dumps(payload).encode(),
        stderr=b"",
    )


class PdfWorkerProtocolTests(unittest.TestCase):
    def test_valid_protocol_transforms_only_bounded_rows(self):
        with patch("nivon.maritime.isolated_pdf_extract.subprocess.run",
                   return_value=completed()) as proc:
            tables = extract_pdf_tables_isolated(FAKE_PDF)
            self.assertEqual(tables[0].page_number, 1)
            self.assertEqual(tables[0].rows[1][1], "DUV-TEST")
            args = proc.call_args
            self.assertEqual(args.kwargs["input"], FAKE_PDF)
            self.assertTrue(args.kwargs["close_fds"])
            self.assertIn("pdf_extraction_worker", args.args[0][-1])

    def test_worker_failure_refuses_output(self):
        with patch("nivon.maritime.isolated_pdf_extract.subprocess.run",
                   return_value=completed(returncode=2)):
            with self.assertRaisesRegex(ValueError, "failed"):
                extract_pdf_tables_isolated(FAKE_PDF)

    def test_worker_sha_mismatch_refuses_substitution(self):
        with patch("nivon.maritime.isolated_pdf_extract.subprocess.run",
                   return_value=completed(digest="0" * 64)):
            with self.assertRaisesRegex(ValueError, "matching original bytes"):
                extract_pdf_tables_isolated(FAKE_PDF)

    def test_worker_version_mismatch(self):
        payload = {"schema_version": 2, "source_sha256": hashlib.sha256(FAKE_PDF).hexdigest(),
                   "tables": [{"page_number": 1, "rows": [["x"]]}]}
        with patch("nivon.maritime.isolated_pdf_extract.subprocess.run",
                   return_value=completed(payload=payload)):
            with self.assertRaisesRegex(ValueError, "matching original bytes"):
                extract_pdf_tables_isolated(FAKE_PDF)

    def test_worker_timeout_kills_processing(self):
        with patch("nivon.maritime.isolated_pdf_extract.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(["pdf_worker"], 25)):
            with self.assertRaisesRegex(ValueError, "timed out"):
                extract_pdf_tables_isolated(FAKE_PDF)

    def test_worker_rejects_bad_json(self):
        with patch("nivon.maritime.isolated_pdf_extract.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=b"{BAD}", stderr=b"")):
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                extract_pdf_tables_isolated(FAKE_PDF)

    def test_worker_refuses_bad_row_types(self):
        with patch("nivon.maritime.isolated_pdf_extract.subprocess.run",
                   return_value=completed(tables=[
                       {"page_number": 1, "rows": [["OK", 123]]}
                   ])):
            with self.assertRaisesRegex(ValueError, "text cell invalid"):
                extract_pdf_tables_isolated(FAKE_PDF)

    def test_worker_refuses_bad_page_index_and_empty_rows(self):
        for item in ({"page_number": 0, "rows": [["OK"]]},
                     {"page_number": 1, "rows": []}):
            with self.subTest(item=item):
                with patch("nivon.maritime.isolated_pdf_extract.subprocess.run",
                           return_value=completed(tables=[item])):
                    with self.assertRaisesRegex(ValueError, "page/row schema"):
                        extract_pdf_tables_isolated(FAKE_PDF)

    def test_worker_rejects_absent_pdf_signature_before_launch(self):
        with patch("nivon.maritime.isolated_pdf_extract.subprocess.run") as proc:
            with self.assertRaisesRegex(ValueError, "signature"):
                extract_pdf_tables_isolated(b"not an actual PDF")
            proc.assert_not_called()

    def test_worker_rejects_bad_timeout_before_launch(self):
        with patch("nivon.maritime.isolated_pdf_extract.subprocess.run") as proc:
            with self.assertRaisesRegex(ValueError, "timeout"):
                extract_pdf_tables_isolated(FAKE_PDF, timeout_seconds=0)
            proc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
