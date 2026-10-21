"""Synthetic programme revision tests: neither identity nor actual shipment proof."""
from dataclasses import replace
from datetime import datetime
import tempfile
import unittest
from pathlib import Path

from nivon.maritime.maritime_store import MaritimeStore
from nivon.maritime.official_lineup_bridge import PdfProgramReference
from nivon.maritime.pdf_programme_ledger import PdfProgrammeEdition, PdfProgrammeLedger
from nivon.maritime.pdf_programme_revisions import (
    CLASSIFICATION, compare_pdf_programme_asof, compare_pdf_programme_editions,
)


def row(*, number="EXPORT_OESTE:PRG-5", product="SOJA", tonnage=10000.0,
        eta="21/10/2026 09:00", complete=True, source_row=1, duv=None,
        vessel="NAVIO SINTETICO"):
    return PdfProgramReference(
        source_row=source_row,
        vessel_name=vessel, programme_number=number,
        explicit_duv=duv, eta_text=eta,
        eta_fully_declared=complete, product=product,
        planned_volume_t=tonnage,
    )


def edition(*, port="PARANAGUA", source="PR_SINTETICA", series="EXPORT_OESTE",
            collection="2026-10-20T12:00:00+00:00",
            published="2026-10-20T11:00:00+00:00", proof="PUB_PROOF",
            reference="2026-10-20", digest="a" * 64, rows=None,
            excluded=1):
    if port == "ITAQUI":
        series = None
    rows = tuple(rows if rows is not None else [row()])
    return PdfProgrammeEdition(
        port_id=port, source_id=source, series=series,
        source_url=("https://www.portodoitaqui.com/doc.pdf" if port == "ITAQUI"
                    else "https://www.portosdoparana.pr.gov.br/doc.pdf"),
        source_sha256=digest, collected_at=collection,
        reference_date=reference, competence=reference[:7],
        published_at=published, publication_evidence_id=proof,
        source_rows=len(rows), excluded_call_rows=excluded,
        rows=rows,
    )


def updated(*, rows=None, digest="b" * 64, published="2026-10-20T15:30:00+00:00",
            collection="2026-10-20T16:00:00+00:00", **kw):
    return edition(rows=rows, digest=digest, published=published,
                   collection=collection, **kw)


def fields(old, new):
    return {change.field: change for change in compare_pdf_programme_editions(old, new)}


def compare_db(db, before="2026-10-20T12:30:00+00:00",
               after="2026-10-20T17:00:00+00:00",
               port="PARANAGUA", source="PR_SINTETICA", series="EXPORT_OESTE",
               authorized=True):
    return compare_pdf_programme_asof(
        db, port_id=port, source_id=source, series=series,
        earlier_as_of=before, later_as_of=after,
        read_authorized=authorized,
    )


class PdfProgrammeRevisionTests(unittest.TestCase):
    def test_unchanged_programme_has_no_false_movement(self):
        self.assertEqual(compare_pdf_programme_editions(edition(), updated()), ())

    def test_eta_change_is_revision_not_ship_arrival(self):
        changes = fields(edition(), updated(rows=[row(eta="22/10/2026 10:30")]))
        self.assertEqual(changes["eta_text_declared"].before, "21/10/2026 09:00")
        self.assertEqual(changes["eta_text_declared"].after, "22/10/2026 10:30")
        self.assertEqual(changes["eta_text_declared"].classification, CLASSIFICATION)

    def test_volume_change_never_means_realized_tonnes(self):
        changes = fields(edition(), updated(rows=[row(tonnage=16000.0)]))
        self.assertEqual(changes["planned_volume_t_declared"].after, 16000.0)
        self.assertNotIn("realized", changes["planned_volume_t_declared"].field)

    def test_single_row_product_revision_is_only_declared(self):
        changes = fields(edition(), updated(rows=[row(product="MILHO")]))
        self.assertEqual(changes["product_declared"].before, "SOJA")
        self.assertEqual(changes["product_declared"].after, "MILHO")
        self.assertEqual(changes["product_declared"].programme_number, "EXPORT_OESTE:PRG-5")

    def test_added_programme_is_not_new_vessel(self):
        changes = fields(edition(), updated(rows=[
            row(), row(source_row=2, number="EXPORT_OESTE:PRG-10", product="MILHO")
        ]))
        self.assertIn("new_programme_reference_not_new_vessel", changes)
        self.assertEqual(changes["new_programme_reference_not_new_vessel"].after, 1)

    def test_missing_programme_is_not_departure_or_cancellation(self):
        changes = fields(edition(rows=[row(), row(
            source_row=2, number="EXPORT_OESTE:PRG-10", product="MILHO")]),
            updated(rows=[row()]))
        self.assertIn("programme_not_listed_in_later_edition_unconfirmed", changes)
        self.assertIsNone(changes["programme_not_listed_in_later_edition_unconfirmed"].after)

    def test_two_products_one_programme_are_matched_by_product(self):
        first = edition(rows=[row(), row(source_row=2, product="MILHO", tonnage=2000.0)],
                        excluded=2)
        next_one = updated(rows=[
            row(source_row=1, product="MILHO", tonnage=3000.0),
            row(source_row=2, product="SOJA", tonnage=15000.0),
        ])
        changes = compare_pdf_programme_editions(first, next_one)
        self.assertEqual(len(changes), 2)
        self.assertEqual({x.field for x in changes}, {"planned_volume_t_declared"})
        self.assertEqual({x.after for x in changes}, {3000.0, 15000.0})

    def test_duplicate_same_product_rows_cannot_be_paired_by_order(self):
        first = edition(rows=[row(), row(source_row=2, tonnage=13000.0)], excluded=2)
        next_one = updated(rows=[row(tonnage=14000.0), row(source_row=2)])
        changes = compare_pdf_programme_editions(first, next_one)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].field, "ambiguous_product_lot_lines_unmatched")
        self.assertNotIn("planned_volume_t_declared", {x.field for x in changes})

    def test_multi_lot_missing_product_label_is_ambiguous(self):
        first = edition(rows=[row(), row(source_row=2, product=None)], excluded=2)
        changes = compare_pdf_programme_editions(first, updated(rows=[
            row(), row(source_row=2, product="MILHO")
        ]))
        self.assertEqual(changes[0].field, "ambiguous_product_lot_lines_unmatched")

    def test_product_mix_difference_is_not_a_confirmed_new_lot(self):
        first = edition(rows=[row(), row(source_row=2, product="MILHO")], excluded=2)
        next_one = updated(rows=[row(), row(source_row=2, product="TRIGO")])
        changes = compare_pdf_programme_editions(first, next_one)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].field, "unmatched_product_labels_unconfirmed")
        self.assertEqual(changes[0].before, "milho")
        self.assertEqual(changes[0].after, "trigo")

    def test_imo_and_name_not_used_as_missing_programme_identity(self):
        first = edition(rows=[row(number=None)], excluded=1)
        next_one = updated(rows=[row(number=None, vessel="NAVIO SINTETICO", tonnage=20000)])
        changes = compare_pdf_programme_editions(first, next_one)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].field, "unidentified_rows_not_reconciled")
        self.assertEqual(changes[0].before, 1)
        self.assertEqual(changes[0].after, 1)

    def test_no_programme_number_does_not_fake_add_or_remove(self):
        first = edition(rows=[row(number=None)], excluded=1)
        second = updated(rows=[row(number="EXPORT_OESTE:PRG-8")])
        changes = compare_pdf_programme_editions(first, second)
        self.assertEqual({x.field for x in changes}, {
            "unidentified_rows_not_reconciled", "new_programme_reference_not_new_vessel",
        })

    def test_source_scope_isolation(self):
        for new in (
            updated(port="ITAQUI", source="PR_SINTETICA",
                    rows=[row(number=None)], excluded=1),
            updated(source="OTHER"),
            updated(series="EXPORT_LESTE",
                    rows=[row(number="EXPORT_LESTE:PRG-5")]),
        ):
            with self.subTest(port=new.port_id, source=new.source_id, series=new.series):
                with self.assertRaisesRegex(ValueError, "port, source and series"):
                    compare_pdf_programme_editions(edition(), new)

    def test_cannot_compare_across_reference_date_even_same_number(self):
        with self.assertRaisesRegex(ValueError, "not proven stable"):
            compare_pdf_programme_editions(edition(), updated(
                reference="2026-10-21", rows=[row()]))
        with self.assertRaisesRegex(ValueError, "not proven stable"):
            compare_pdf_programme_editions(edition(), updated(
                reference="2026-10-19", rows=[row()]))

    def test_collection_order_is_strict(self):
        with self.assertRaisesRegex(ValueError, "strictly later"):
            compare_pdf_programme_editions(edition(), edition())
        with self.assertRaisesRegex(ValueError, "strictly later"):
            compare_pdf_programme_editions(updated(), edition())

    def test_eta_precision_downgrade_not_inferred_true(self):
        changes = fields(edition(), updated(rows=[
            row(eta="21/10/2026", complete=False)
        ]))
        self.assertFalse(changes["eta_fully_declared"].after)
        self.assertEqual(changes["eta_text_declared"].after, "21/10/2026")

    def test_renamed_vessel_does_not_migrate_to_another_programme(self):
        changes = fields(edition(), updated(rows=[
            row(vessel="NAVIO SINTETICO II")
        ]))
        self.assertIn("vessel_name_declared", changes)
        self.assertEqual(changes["vessel_name_declared"].classification, CLASSIFICATION)

    def test_explicit_duv_newly_present_still_only_declaration(self):
        changes = fields(edition(), updated(rows=[
            row(duv="DUV-9001")
        ]))
        self.assertEqual(changes["explicit_duv_field"].after, "DUV-9001")
        self.assertEqual(changes["explicit_duv_field"].classification, CLASSIFICATION)

    def test_asof_previous_edition_not_visible_until_collected(self):
        with MaritimeStore() as store:
            db = PdfProgrammeLedger(store)
            db.save(edition(), storage_authorized=True)
            db.save(updated(rows=[row(tonnage=90000)]), storage_authorized=True)
            one = compare_db(db)
            self.assertEqual(one.status, "PROGRAMME_REVISION_ONLY_NOT_PHYSICAL_OPERATION")
            self.assertEqual(one.summary()["change_count"], 1)
            self.assertIsNone(one.summary()["realized_tonnage_t"])
            self.assertFalse(one.summary()["publication_allowed"])

    def test_asof_gated_if_earlier_has_no_published_document(self):
        with MaritimeStore() as store:
            db = PdfProgrammeLedger(store)
            db.save(updated(), storage_authorized=True)
            result = compare_db(db)
            self.assertEqual(result.status, "DATA_GATED")
            self.assertIsNone(result.summary()["change_count"])
            self.assertIsNone(result.summary()["source_document_changed"])

    def test_asof_missing_publication_never_leaks_in_comparison(self):
        with MaritimeStore() as store:
            db = PdfProgrammeLedger(store)
            db.save(edition(published=None, proof=None), storage_authorized=True)
            self.assertEqual(compare_db(db).status, "DATA_GATED")

    def test_asof_same_edition_does_not_infer_arrival_after_eta(self):
        with MaritimeStore() as store:
            db = PdfProgrammeLedger(store)
            db.save(edition(), storage_authorized=True)
            result = compare_db(db, after="2026-10-23T17:00:00+00:00")
            self.assertEqual(result.status, "SAME_PROGRAMME_EDITION")
            self.assertEqual(result.summary()["changes"], [])
            self.assertIsNone(result.summary()["confirmed_departures"])
            self.assertIsNone(result.summary()["confirmed_port_calls"])

    def test_different_document_hash_without_row_change_is_document_revision(self):
        with MaritimeStore() as store:
            db = PdfProgrammeLedger(store)
            db.save(edition(), storage_authorized=True)
            db.save(updated(), storage_authorized=True)
            result = compare_db(db)
            self.assertEqual(result.summary()["change_count"], 0)
            self.assertTrue(result.summary()["source_document_changed"])

    def test_query_earlier_later_order_and_naive_time_fail_closed(self):
        with MaritimeStore() as store:
            db = PdfProgrammeLedger(store)
            with self.assertRaisesRegex(ValueError, "strictly follow"):
                compare_db(db, before="2026-10-21T10:00:00+00:00",
                           after="2026-10-20T10:00:00+00:00")
            with self.assertRaises(ValueError):
                compare_db(db, before="2026-10-20T10:00:00")

    def test_asof_read_denied_by_default(self):
        with MaritimeStore() as store:
            db = PdfProgrammeLedger(store)
            db.save(edition(), storage_authorized=True)
            with self.assertRaises(PermissionError):
                compare_db(db, authorized=False)

    def test_backup_restored_programme_revisions_are_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "maritime.sqlite"
            backup = Path(tmp) / "backup.sqlite"
            with MaritimeStore(file_path) as store:
                db = PdfProgrammeLedger(store)
                db.save(edition(), storage_authorized=True)
                db.save(updated(rows=[row(tonnage=11000)]), storage_authorized=True)
                before = compare_db(db).summary()
                store.backup(backup, backup_authorized=True)
            self.assertEqual(MaritimeStore.validate_restore(backup)["pdf_programme_edition_rows"], 2)
            with MaritimeStore(backup) as store:
                after = compare_db(PdfProgrammeLedger(store)).summary()
            self.assertEqual(before, after)

    def test_asof_cross_reference_date_is_blocked_even_if_both_known(self):
        with MaritimeStore() as store:
            db = PdfProgrammeLedger(store)
            db.save(edition(), storage_authorized=True)
            db.save(updated(reference="2026-10-21"), storage_authorized=True)
            with self.assertRaisesRegex(ValueError, "not proven stable"):
                compare_db(db)

    def test_compare_never_mutates_input_rows(self):
        first, second = edition(), updated(rows=[row(product="MILHO", tonnage=5000)])
        before = repr((first, second))
        compare_pdf_programme_editions(first, second)
        self.assertEqual(before, repr((first, second)))


if __name__ == "__main__":
    unittest.main()
