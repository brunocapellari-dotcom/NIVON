"""Multi-edition synthetic batch integration: rollback, as-of, rights, revisions."""
import hashlib
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from unittest.mock import patch

from nivon.maritime.maritime_store import MaritimeStore
from nivon.maritime.pdf_programme_ledger import PdfProgrammeLedger
from nivon.maritime.offline_pdf_batch import (
    OfflinePdfEdition, OfflineRightsAttestation, run_offline_pdf_batch,
)
from test_maritime_pdf_lineup_bridge import (
    contract, document, paranagua, tables_paranagua, itaqui, tables_itaqui,
)


@contextmanager
def extracted_tables(*table_editions):
    """Only page extraction is mocked; canonical collector and ledgers are real."""
    with patch("nivon.portos_automaticos.extract_pdf_tables", side_effect=table_editions):
        with patch("nivon.maritime.official_lineup_bridge.extract_pdf_tables",
                   side_effect=table_editions):
            yield


def authorized(*, storage=True, reading=True, parsing=True):
    return OfflineRightsAttestation(
        evidence_reference="SYNTHETIC_RIGHTS_ASSERTION_NOT_REAL",
        reviewed_by="SYNTHETIC_REVIEWER",
        rights_status="ATTESTED",
        offline_processing=parsing, store_derived=storage, read_derived=reading,
    )


def input_doc(*, port="PARANAGUA", collected="2026-10-20T12:00:00Z",
              published="2026-10-20T11:00:00Z", reference=None,
              seed=b"A", rights=None, sha_valid=True):
    checked = contract(port)
    if reference is not None:
        checked = replace(checked, data_referencia=date.fromisoformat(reference))
    recorded = document(port, stamp=collected)
    payload = recorded["conteudo"] + seed
    recorded["conteudo"] = payload
    recorded["sha256"] = hashlib.sha256(payload).hexdigest() if sha_valid else "0" * 64
    recorded["bytes"] = len(payload)
    return OfflinePdfEdition(
        checked, recorded, authorized() if rights is None else rights,
        published_at=published,
        publication_evidence_id="SYNTHETIC_PUBLISH_PROOF" if published else None,
    )


def programmed(*, eta="21/10/2026 09:00", volume="23.000,00", prog="PRG-5"):
    return tables_paranagua(paranagua(duv="", eta=eta, volume=volume, prog=prog))


def run(store, entries, tables, *, commit, asof="2026-10-20T17:00:00Z"):
    with extracted_tables(*tables):
        return run_offline_pdf_batch(tuple(entries), store=store, as_of=asof, commit=commit)


class OfflineMaritimeBatchTests(unittest.TestCase):
    def test_two_document_batch_commits_atomic_and_reports_eta_change(self):
        first = input_doc()
        second = input_doc(collected="2026-10-20T16:00:00Z",
                           published="2026-10-20T15:00:00Z", seed=b"B")
        with MaritimeStore() as store:
            out = run(store, [first, second], [
                programmed(), programmed(eta="21/10/2026 11:30")
            ], commit=True)
            self.assertEqual(out["edition_writes"]["inserted"], 2)
            self.assertEqual(len(out["revisions"]), 1)
            self.assertEqual(out["revisions"][0]["changes"][0]["field"], "eta_text_declared")
            self.assertEqual(out["revisions"][0]["change_count"], 1)
            self.assertIsNone(out["arrivals_confirmed"])
            self.assertIsNone(out["port_call_count"])
            self.assertFalse(out["publication_allowed"])
            self.assertEqual(PdfProgrammeLedger(store).count_editions(
                port_id="PARANAGUA", source_id="OFFICIAL_PARANAGUA_TEST",
                series="EXPORT_OESTE", read_authorized=True), 2)

    def test_idempotent_batch_on_repeat_no_extra_version(self):
        first = input_doc()
        second = input_doc(collected="2026-10-20T16:00:00Z", seed=b"B",
                           published="2026-10-20T15:00:00Z")
        with MaritimeStore() as store:
            run(store, [first, second], [programmed(), programmed()], commit=True)
            out = run(store, [first, second], [programmed(), programmed()], commit=True)
            self.assertEqual(out["edition_writes"], {"inserted": 0, "already_present": 2})
            self.assertEqual(len(out["revisions"]), 1)
            self.assertEqual(out["revisions"][0]["change_count"], 0)

    def test_dryrun_reads_simulated_two_versions_without_inserting(self):
        first = input_doc()
        second = input_doc(collected="2026-10-20T16:00:00Z", seed=b"B",
                           published="2026-10-20T15:00:00Z")
        with MaritimeStore() as store:
            out = run(store, [first, second], [
                programmed(), programmed(volume="25.000,00")
            ], commit=False)
            self.assertEqual(out["execution_mode"], "DRY_RUN_NO_STORAGE")
            self.assertEqual(out["revisions"][0]["changes"][0]["field"],
                             "planned_volume_t_declared")
            self.assertEqual(out["edition_writes"]["inserted"], 0)
            self.assertEqual(PdfProgrammeLedger(store).count_editions(
                port_id="PARANAGUA", source_id="OFFICIAL_PARANAGUA_TEST",
                series="EXPORT_OESTE", read_authorized=True), 0)

    def test_invalid_second_pdf_prevents_any_write(self):
        first = input_doc()
        bad = input_doc(seed=b"B", collected="2026-10-20T16:00:00Z",
                        sha_valid=False)
        with MaritimeStore() as store:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                run(store, [first, bad], [
                    programmed(), programmed()
                ], commit=True)
            self.assertEqual(PdfProgrammeLedger(store).count_editions(
                port_id="PARANAGUA", source_id="OFFICIAL_PARANAGUA_TEST",
                series="EXPORT_OESTE", read_authorized=True), 0)

    def test_conflict_mid_batch_rolls_back_first_insert(self):
        existing = input_doc(collected="2026-10-20T16:00:00Z",
                             published="2026-10-20T15:00:00Z", seed=b"OLD")
        first = input_doc(seed=b"NEW")
        conflict = input_doc(collected="2026-10-20T16:00:00Z",
                             published="2026-10-20T15:00:00Z", seed=b"DIFFERENT")
        with MaritimeStore() as store:
            run(store, [existing], [programmed()], commit=True)
            with self.assertRaisesRegex(ValueError, "conflicting"):
                run(store, [first, conflict], [
                    programmed(), programmed(eta="21/10/2026 12:00")
                ], commit=True)
            ledger = PdfProgrammeLedger(store)
            self.assertEqual(ledger.count_editions(
                port_id="PARANAGUA", source_id="OFFICIAL_PARANAGUA_TEST",
                series="EXPORT_OESTE", read_authorized=True), 1)

    def test_mixed_ports_do_not_cross_reconcile(self):
        west = input_doc()
        itaqui_doc = input_doc(port="ITAQUI", seed=b"I")
        with MaritimeStore() as store:
            out = run(store, [west, itaqui_doc],
                      [programmed(), tables_itaqui(itaqui(duv=""))], commit=True)
            self.assertEqual(out["edition_writes"]["inserted"], 2)
            self.assertEqual(len(out["revisions"]), 0)
            self.assertEqual({d["port_id"] for d in out["documents"]},
                             {"PARANAGUA", "ITAQUI"})

    def test_across_reference_dates_refuses_to_unify_prog_identity(self):
        first = input_doc()
        second = input_doc(reference="2026-10-19", seed=b"B",
                           collected="2026-10-20T16:00:00Z",
                           published="2026-10-20T15:00:00Z")
        with MaritimeStore() as store:
            out = run(store, [first, second], [programmed(), programmed()],
                      commit=True)
            self.assertEqual(out["revisions"][0]["status"],
                             "REFERENCE_DATE_BOUNDARY_NO_ID_CONTINUITY")
            self.assertIsNone(out["revisions"][0]["changes"])

    def test_missing_publication_is_not_known_asof(self):
        doc = input_doc(published=None)
        with MaritimeStore() as store:
            out = run(store, [doc], [programmed()], commit=True)
            self.assertFalse(out["documents"][0]["document_known_as_of"])
            self.assertEqual(out["revisions"], [])
            self.assertEqual(PdfProgrammeLedger(store).history_asof(
                port_id="PARANAGUA", source_id="OFFICIAL_PARANAGUA_TEST",
                series="EXPORT_OESTE", as_of="2026-10-30T12:00:00Z",
                read_authorized=True), ())

    def test_cutoff_before_collection_has_no_visible_revisions(self):
        item = input_doc()
        with MaritimeStore() as store:
            out = run(store, [item], [programmed()], commit=True,
                      asof="2026-10-20T11:30:00Z")
            self.assertFalse(out["documents"][0]["document_known_as_of"])
            self.assertEqual(out["revisions"], [])

    def test_denied_processing_rights_blocks_batch(self):
        item = input_doc(rights=authorized(parsing=False))
        with MaritimeStore() as store:
            with self.assertRaises(PermissionError):
                run(store, [item], [programmed()], commit=True)

    def test_denied_derived_storage_blocks_before_parsing(self):
        item = input_doc(rights=authorized(storage=False))
        with MaritimeStore() as store:
            with self.assertRaisesRegex(PermissionError, "storage"):
                run(store, [item], [programmed()], commit=True)

    def test_denied_read_blocks_even_dryrun(self):
        item = input_doc(rights=authorized(reading=False))
        with MaritimeStore() as store:
            with self.assertRaisesRegex(PermissionError, "history"):
                run(store, [item], [programmed()], commit=False)

    def test_batch_bound_and_unknown_entity_rejected(self):
        with MaritimeStore() as store:
            with self.assertRaisesRegex(ValueError, "1 and 24"):
                run_offline_pdf_batch((), store=store,
                    as_of="2026-10-20T17:00:00Z")
            with self.assertRaises(TypeError):
                run_offline_pdf_batch(("BAD",), store=store,
                    as_of="2026-10-20T17:00:00Z")

    def test_history_limit_never_silently_truncates(self):
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            items = [input_doc(), input_doc(collected="2026-10-20T16:00:00Z",
                                            published="2026-10-20T15:00:00Z",seed=b"B")]
            run(store, items, [programmed(), programmed()], commit=True)
            with self.assertRaisesRegex(ValueError, "exceeds max_editions"):
                ledger.history_asof(
                    port_id="PARANAGUA", source_id="OFFICIAL_PARANAGUA_TEST",
                    series="EXPORT_OESTE", as_of="2026-10-20T17:00:00Z",
                    read_authorized=True, max_editions=1)

    def test_historic_doc_added_after_first_run_generates_one_revision(self):
        first = input_doc()
        second = input_doc(collected="2026-10-20T16:00:00Z",
                           published="2026-10-20T15:00:00Z", seed=b"B")
        with MaritimeStore() as store:
            run(store, [first], [programmed()], commit=True)
            next_run = run(store, [second], [
                programmed(eta="21/10/2026 13:00")
            ], commit=True)
            self.assertEqual(next_run["edition_writes"]["inserted"], 1)
            self.assertEqual(len(next_run["revisions"]), 1)
            self.assertEqual(next_run["revisions"][0]["changes"][0]["field"],
                             "eta_text_declared")


if __name__ == "__main__":
    unittest.main()
