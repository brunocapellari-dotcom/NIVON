"""Synthetic PDF programme ledger regressions; no source access or real rights.

Programme references are deliberately not DUVs and never count realized calls.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import tempfile
import unittest

from nivon.maritime.maritime_store import MaritimeStore
from nivon.maritime.official_lineup_bridge import LineupBridgeResult, PdfProgramReference
from nivon.maritime.pdf_programme_ledger import (
    PdfProgrammeEdition, PdfProgrammeLedger, edition_from_pdf_bridge,
)

STAMP = "2026-10-20T12:00:00+00:00"
SOURCE = "PORTOS_PARANAGUA_SYNTHETIC"
REFERENCE = "2026-10-20"


def programme(num="EXPORT_OESTE:PRG-5", *, row=1, duv=None, volume=35000.0):
    return PdfProgramReference(
        source_row=row, vessel_name="VESSEL SYNTHETIC",
        programme_number=num, explicit_duv=duv,
        eta_text="21/10/2026 09:00", eta_fully_declared=True,
        product="SOJA" if row == 1 else "MILHO",
        planned_volume_t=volume,
    )


def bridge(*, port="PARANAGUA", source=None, series="EXPORT_OESTE",
           stamp=STAMP, digest="a" * 64, rows=None):
    if port == "ITAQUI":
        series = None
    items = tuple(rows if rows is not None else [programme(
        num=None if port == "ITAQUI" else series + ":PRG-5"
    )])
    # These synthetic PDF rows lack DUV and therefore ALL remain excluded
    # from full, unique port-call vintage promotion.
    return LineupBridgeResult(
        port_id=port, source_id=source or (
            "PORTO_ITAQUI_SYNTHETIC" if port == "ITAQUI" else SOURCE),
        source_url=("https://www.portodoitaqui.com/test.pdf" if port == "ITAQUI"
                    else "https://www.portosdoparana.pr.gov.br/test.pdf"),
        document_sha256=digest,
        collected_at=stamp,
        candidates=(),
        excluded=tuple({"row": str(i), "reason": "explicit_duv_missing_or_invalid"}
                       for i in range(1, len(items) + 1)),
        source_rows=len(items),
        pdf_program_rows=items,
        pdf_series=series,
    )


def edition(*, stamp=STAMP, digest="a" * 64, rows=None,
            published="2026-10-20T11:00:00+00:00", proof="synthetic-proof",
            port="PARANAGUA", series="EXPORT_OESTE"):
    doc = bridge(port=port, series=series, stamp=stamp, digest=digest, rows=rows)
    return edition_from_pdf_bridge(
        doc, reference_date=REFERENCE, competence="2026-10",
        published_at=published, publication_evidence_id=proof,
    )


def look(ledger, *, at="2026-10-20T12:30:00+00:00",
         port="PARANAGUA", source=SOURCE, series="EXPORT_OESTE",
         authorized=True):
    return ledger.select_asof(
        port_id=port, source_id=source, series=series,
        as_of=at, read_authorized=authorized,
    )


class ProgrammeLedgerTests(unittest.TestCase):
    def test_no_rights_read_write_denied(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            with self.assertRaises(PermissionError):
                ledger.save(edition())
            with self.assertRaises(PermissionError):
                look(ledger, authorized=False)
            with self.assertRaises(PermissionError):
                ledger.count_editions(port_id="PARANAGUA", source_id=SOURCE, series="EXPORT_OESTE")

    def test_pdf_without_duv_is_still_a_programme_edition(self):
        doc = edition()
        self.assertEqual(doc.excluded_call_rows, 1)
        self.assertIsNone(doc.rows[0].explicit_duv)
        self.assertEqual(doc.rows[0].programme_number, "EXPORT_OESTE:PRG-5")
        self.assertEqual(doc.provenance()["evidence_class"], "PROGRAMME_REFERENCE_NOT_PORT_CALL")

    def test_unknown_publication_not_visible_asof(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            self.assertTrue(ledger.save(edition(published=None, proof=None), storage_authorized=True))
            r = look(ledger, at="2026-10-30T12:30:00+00:00")
            self.assertEqual(r.status, "DATA_GATED")
            self.assertIsNone(r.summary()["programme_pdf_rows"])
            self.assertIsNone(r.summary()["verified_port_call_count"])

    def test_exact_replay_is_idempotent(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            self.assertTrue(ledger.save(edition(), storage_authorized=True))
            self.assertFalse(ledger.save(edition(), storage_authorized=True))
            self.assertEqual(ledger.count_editions(port_id="PARANAGUA", source_id=SOURCE,
                                                    series="EXPORT_OESTE", read_authorized=True), 1)

    def test_same_collection_different_pdf_is_conflict_not_overwrite(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(), storage_authorized=True)
            with self.assertRaisesRegex(ValueError, "conflicting"):
                ledger.save(edition(digest="b" * 64), storage_authorized=True)
            self.assertEqual(look(ledger).edition.source_sha256, "a" * 64)

    def test_same_hash_different_row_not_silent(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(), storage_authorized=True)
            with self.assertRaisesRegex(ValueError, "conflicting"):
                ledger.save(edition(rows=[programme(volume=12345.0)]), storage_authorized=True)

    def test_backtest_cannot_see_future_collection_or_publication(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(), storage_authorized=True)
            ledger.save(edition(
                stamp="2026-10-20T18:00:00+00:00", digest="b" * 64,
                published="2026-10-20T16:00:00+00:00",
            ), storage_authorized=True)
            self.assertEqual(look(ledger).edition.source_sha256, "a" * 64)
            self.assertEqual(look(ledger, at="2026-10-20T19:00:00+00:00").edition.source_sha256, "b" * 64)

    def test_published_but_collected_later_cannot_leak(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(stamp="2026-10-20T18:00:00+00:00"), storage_authorized=True)
            self.assertEqual(look(ledger).status, "DATA_GATED")

    def test_one_programme_two_product_rows_does_not_count_two_ships(self):
        rows = [programme(row=1), programme(row=2, volume=23000.0)]
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(rows=rows), storage_authorized=True)
            summary = look(ledger).summary()
            self.assertEqual(summary["programme_pdf_rows"], 2)
            self.assertEqual(summary["programme_numbers_declared"], 1)
            self.assertIsNone(summary["verified_port_call_count"])
            self.assertIsNone(summary["realized_volume_t"])
            self.assertFalse(summary["publication_allowed"])

    def test_paranagua_series_are_disjoint(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(), storage_authorized=True)
            west = look(ledger)
            east = look(ledger, series="EXPORT_LESTE")
            self.assertIsNotNone(west.edition)
            self.assertIsNone(east.edition)
            self.assertEqual(east.status, "DATA_GATED")

    def test_itaqui_and_paranagua_never_mix(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(port="ITAQUI", series=None), storage_authorized=True)
            self.assertEqual(look(ledger).status, "DATA_GATED")
            itaqui = look(ledger, port="ITAQUI", series=None, source="PORTO_ITAQUI_SYNTHETIC")
            self.assertEqual(itaqui.summary()["programme_pdf_rows"], 1)
            self.assertEqual(itaqui.summary()["programme_numbers_declared"], 0)

    def test_future_unknown_cannot_be_changed_to_realized(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(), storage_authorized=True)
            r = look(ledger).summary()
            self.assertIsNone(r["actual_arrivals"])
            self.assertIsNone(r["realized_volume_t"])
            self.assertIsNone(r["verified_port_call_count"])

    def test_missing_source_rows_fails_no_false_complete_edition(self):
        doc = bridge()
        incomplete = replace(doc, source_rows=2)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            edition_from_pdf_bridge(incomplete, reference_date=REFERENCE, competence="2026-10")

    def test_html_bridge_cannot_persist_as_pdf_programming(self):
        doc = replace(bridge(), port_id="SANTOS")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            edition_from_pdf_bridge(doc, reference_date=REFERENCE, competence="2026-10")

    def test_publication_evidence_comes_only_externally(self):
        item = edition(published=None, proof=None)
        self.assertIsNone(item.published_utc)
        with self.assertRaises(ValueError):
            edition(published="2026-10-20T11:00:00+00:00", proof=None)

    def test_duplicate_row_numbers_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            edition(rows=[programme(row=1), programme(row=1)])

    def test_wrong_series_reference_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside series"):
            edition(rows=[programme(num="EXPORT_LESTE:PRG-5")])

    def test_source_url_not_allowed_from_different_authority(self):
        source = edition()
        with self.assertRaisesRegex(ValueError, "unregistered authority"):
            replace(source, source_url="https://www.portodoitaqui.com/wrong.pdf")

    def test_https_spoofed_domain_credentials_and_custom_port_refused(self):
        source = edition()
        for url in (
            "https://www.portosdoparana.pr.gov.br.evil.example/f.pdf",
            "https://user:password@www.portosdoparana.pr.gov.br/f.pdf",
            "https://www.portosdoparana.pr.gov.br:444/f.pdf",
            "http://www.portosdoparana.pr.gov.br/f.pdf",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "authority"):
                    replace(source, source_url=url)

    def test_programme_identifier_must_have_value_after_series(self):
        with self.assertRaisesRegex(ValueError, "outside series"):
            edition(rows=[programme(num="EXPORT_OESTE:")])

    def test_nonfinite_or_negative_tonnage_refused(self):
        for value in (-1.0, float("inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "tonnage"):
                    edition(rows=[programme(volume=value)])

    def test_corrupt_checksum_fails_on_read(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(), storage_authorized=True)
            store.db.execute("UPDATE maritime_pdf_programme_editions SET payload_json='{}'")
            store.db.commit()
            with self.assertRaisesRegex(ValueError, "checksum"):
                look(ledger)

    def test_corrupt_identity_fails_on_read(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(), storage_authorized=True)
            store.db.execute("UPDATE maritime_pdf_programme_editions SET edition_id=?", ("0" * 64,))
            store.db.commit()
            with self.assertRaisesRegex(ValueError, "identity/metadata"):
                look(ledger)

    def test_file_reopen_and_backup_restore_has_separate_count(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "maritime.sqlite"
            backup = Path(folder) / "maritime_backup.sqlite"
            with MaritimeStore(path) as store:
                ledger = PdfProgrammeLedger(store)
                ledger.save(edition(), storage_authorized=True)
                store.backup(backup, backup_authorized=True)
            restored = MaritimeStore.validate_restore(backup)
            self.assertEqual(restored["integrity"], "ok")
            self.assertEqual(restored["pdf_programme_edition_rows"], 1)
            self.assertEqual(restored["lineup_vintage_rows"], 0)
            with MaritimeStore(backup) as store:
                other = PdfProgrammeLedger(store)
                self.assertEqual(look(other).edition.source_sha256, "a" * 64)

    def test_legacy_backup_reports_no_pdf_programme_editions(self):
        with tempfile.TemporaryDirectory() as folder:
            backup = Path(folder) / "no_programming.sqlite"
            with MaritimeStore() as store:
                store.backup(backup, backup_authorized=True)
            self.assertEqual(
                MaritimeStore.validate_restore(backup)["pdf_programme_edition_rows"], 0,
            )

    def test_paged_longitudinal_history_over_200_documents_without_truncation(self):
        start = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        docs = tuple(edition(
            stamp=(start + timedelta(minutes=i)).isoformat(),
            digest=hashlib.sha256(f"SYNTHETIC-{i}".encode()).hexdigest(),
        ) for i in range(205))
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            for offset in range(0, len(docs), 100):
                ledger.save_batch(docs[offset:offset + 100], storage_authorized=True)
            history = ledger.paged_history_asof(
                port_id="PARANAGUA", source_id=SOURCE, series="EXPORT_OESTE",
                as_of="2026-10-20T20:00:00Z",
                page_size=17, max_total_editions=205,
                read_authorized=True,
            )
            self.assertEqual(len(history), 205)
            self.assertEqual(history[0].source_sha256, docs[0].source_sha256)
            self.assertEqual(history[-1].source_sha256, docs[-1].source_sha256)
            self.assertEqual(len({x.collected_utc for x in history}), 205)
            with self.assertRaisesRegex(ValueError, "exceeds explicit"):
                ledger.paged_history_asof(
                    port_id="PARANAGUA", source_id=SOURCE, series="EXPORT_OESTE",
                    as_of="2026-10-20T20:00:00Z",
                    page_size=30, max_total_editions=204,
                    read_authorized=True,
                )
            with self.assertRaisesRegex(ValueError, "exceeds explicit"):
                ledger.paged_history_asof(
                    port_id="PARANAGUA", source_id=SOURCE, series="EXPORT_OESTE",
                    as_of="2026-10-20T20:00:00Z",
                    max_payload_bytes=20, read_authorized=True,
                )

    def test_paged_audit_separates_unknown_publication_from_known_history(self):
        known = edition()
        unknown = edition(
            stamp="2026-10-20T16:00:00Z", digest="b" * 64,
            published=None, proof=None,
        )
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save_batch((known, unknown), storage_authorized=True)
            options = dict(
                port_id="PARANAGUA", source_id=SOURCE, series="EXPORT_OESTE",
                read_authorized=True, page_size=1,
                as_of="2026-10-20T17:00:00Z",
            )
            self.assertEqual(len(ledger.paged_history_asof(**options)), 1)
            audit = ledger.paged_history_asof(**options, audit_only=True)
            self.assertEqual(len(audit), 2)
            self.assertIsNone(audit[-1].published_utc)
            earlier = ledger.paged_history_asof(
                **{**options, "as_of": "2026-10-20T13:00:00Z"},
                audit_only=True,
            )
            self.assertEqual(len(earlier), 1)
            self.assertEqual(earlier[0].source_sha256, known.source_sha256)

    def test_paged_history_read_is_deny_by_default(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            with self.assertRaises(PermissionError):
                ledger.paged_history_asof(
                    port_id="ITAQUI", source_id="PORTO_ITAQUI_SYNTHETIC",
                    series=None, as_of="2026-10-20T17:00:00Z"
                )

    def test_no_automatic_rights_to_release_even_with_published_snapshot(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(edition(), storage_authorized=True)
            summary = look(ledger).summary()
            self.assertEqual(summary["status"], "PROGRAMME_ONLY_NOT_PORT_CALL")
            self.assertFalse(summary["publication_allowed"])
            self.assertEqual(summary["programme_numbers_declared"], 1)


if __name__ == "__main__":
    unittest.main()
