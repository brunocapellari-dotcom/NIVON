"""Offline synthetic crosswalk dossier tests; never grants rights or port-call ID."""
from dataclasses import replace
import unittest

from nivon.maritime.official_lineup_bridge import PdfProgramReference
from nivon.maritime.pdf_programme_ledger import PdfProgrammeEdition
from nivon.maritime.programme_duv_evidence import (
    ProgrammeDuvEvidence, assess_programme_duv_evidence,
)


def programme(num="EXPORT_OESTE:PROG-15"):
    return PdfProgramReference(
        source_row=1, vessel_name="NAVIO SINTETICO",
        programme_number=num, explicit_duv="DUV-2026-5543", eta_text="22/10/2026 08:30",
        eta_fully_declared=True, product="SOJA", planned_volume_t=20000.0
    )


def edition():
    return PdfProgrammeEdition(
        port_id="PARANAGUA", source_id="PARANAGUA_PROGRAMMING_TEST",
        series="EXPORT_OESTE",
        source_url="https://www.portosdoparana.pr.gov.br/official/synthetic.pdf",
        source_sha256="a" * 64, collected_at="2026-10-20T12:00:00+00:00",
        reference_date="2026-10-20", competence="2026-10",
        published_at="2026-10-20T09:00:00+00:00",
        publication_evidence_id="SYNTHETIC_PUB_PROOF",
        source_rows=1, rows=(programme(),), excluded_call_rows=1
    )


def evidence(**changes):
    fields = dict(
        port_id="PARANAGUA", source_id="PARANAGUA_PROGRAMMING_TEST",
        series="EXPORT_OESTE", reference_date="2026-10-20",
        programme_number="EXPORT_OESTE:PROG-15",
        duv="DUV-2026-5543",
        lineup_source_sha256="a" * 64,
        link_evidence_url="https://www.portosdoparana.pr.gov.br/official/synthetic.pdf",
        link_document_sha256="a" * 64,
        link_evidence_id="DOCUMENTED_DUV_PAIR",
        acquisition_evidence_id="SYNTHETIC_ACQUISITION",
        publication_evidence_id="SYNTHETIC_PUBLISHED_AT",
        published_at="2026-10-20T09:00:00+00:00",
        acquired_at="2026-10-20T12:00:00+00:00",
        reviewed_at="2026-10-20T13:00:00+00:00",
        reviewed_by="SYNTHETIC_INDEPENDENT_REVIEWER",
        evidence_kind="OFFICIAL_SOURCE_EXPLICIT_PAIR",
    )
    fields.update(changes)
    return ProgrammeDuvEvidence(**fields)


def review(records=None, *, at="2026-10-20T14:00:00+00:00",
           licensed=True, inspected=True, snapshot=None):
    return assess_programme_duv_evidence(
        snapshot or edition(), tuple(records if records is not None else [evidence()]),
        as_of=at, source_rights_reviewed=licensed,
        independent_relation_reviewed=inspected,
    )


class DuvCrosswalkEvidenceTests(unittest.TestCase):
    def test_direct_pair_is_only_review_ready_never_canonical(self):
        report = review()
        self.assertEqual(report.status, "CANDIDATE_READY_FOR_EXTERNAL_VERIFICATION")
        self.assertEqual(report.candidate_pairs, (("EXPORT_OESTE:PROG-15", "DUV-2026-5543"),))
        self.assertFalse(report.release_allowed)
        self.assertFalse(report.canonical_duv_link_allowed)
        summary = report.summary()
        self.assertFalse(summary["canonical_duv_link_allowed"])
        self.assertEqual(summary["evidence_class"], "DOCUMENTARY_CANDIDATE_NOT_VERIFIED_PORT_CALL")

    def test_missing_link_evidence_blocks(self):
        result = review(records=[])
        self.assertIn("LINK_EVIDENCE_MISSING", result.rejected_reasons)
        self.assertEqual(result.candidate_pairs, ())

    def test_collection_rights_must_be_reviewed_explicitly(self):
        result = review(licensed=False)
        self.assertIn("SOURCE_RIGHTS_UNREVIEWED", result.rejected_reasons)
        self.assertEqual(result.status, "BLOCKED_UNVERIFIED_DOCUMENTARY_LINK")

    def test_independent_relation_review_required(self):
        result = review(inspected=False)
        self.assertIn("RELATION_NOT_INDEPENDENTLY_REVIEWED", result.rejected_reasons)
        self.assertEqual(result.candidate_pairs, ())

    def test_same_programme_two_distinct_duvs_is_hard_conflict(self):
        result = review(records=[evidence(), evidence(duv="DUV-DIFFERENT")])
        self.assertIn("CONTRADICTORY_DUV_FOR_SAME_PROGRAMME", result.rejected_reasons)
        self.assertEqual(result.candidate_pairs, ())

    def test_repeat_exact_same_documented_pair_does_not_duplicate(self):
        result = review(records=[evidence(), evidence()])
        self.assertEqual(len(result.candidate_pairs), 1)

    def test_future_relation_collection_not_backdated(self):
        result = review(at="2026-10-20T11:00:00+00:00")
        self.assertIn("PROGRAMME_EDITION_FUTURE_ASOF", result.rejected_reasons)
        self.assertIn("LINK_EVIDENCE_FUTURE_ASOF", result.rejected_reasons)

    def test_future_review_does_not_leak_into_past(self):
        result = review(at="2026-10-20T12:30:00+00:00")
        self.assertIn("LINK_EVIDENCE_FUTURE_ASOF", result.rejected_reasons)

    def test_future_publication_of_lineup_blocks(self):
        source = replace(edition(),
            published_at="2026-10-20T11:00:00+00:00",
            collected_at="2026-10-20T12:00:00+00:00")
        self.assertIn("PROGRAMME_EDITION_FUTURE_ASOF",
            review(snapshot=source, at="2026-10-20T10:00:00+00:00").rejected_reasons)

    def test_unknown_publication_does_not_count_as_known_edition(self):
        snap = replace(edition(), published_at=None, publication_evidence_id=None)
        result = review(snapshot=snap)
        self.assertIn("PROGRAMME_EDITION_PUBLICATION_UNPROVEN", result.rejected_reasons)

    def test_programme_scope_must_match_edition_exactly(self):
        for patch in (
            {"source_id": "OTHER"}, {"series": "EXPORT_LESTE",
             "programme_number": "EXPORT_LESTE:PROG-15"},
            {"reference_date": "2026-10-19"},
            {"lineup_source_sha256": "b"*64}
        ):
            with self.subTest(patch=patch):
                self.assertIn("DOCUMENT_SCOPE_MISMATCH",
                    review(records=[evidence(**patch)]).rejected_reasons)

    def test_unknown_programme_cannot_be_linked_by_name(self):
        result = review(records=[evidence(programme_number="EXPORT_OESTE:OTHER")])
        self.assertIn("PROGRAMME_NOT_FOUND_IN_EDITION", result.rejected_reasons)

    def test_imo_or_vessel_name_never_allowed_as_duv(self):
        for candidate in ("", "NAVIO TESTE", "DUV 123", "DUV?", "a"*130):
            with self.subTest(candidate=candidate):
                with self.assertRaisesRegex(ValueError, "valid DUV"):
                    evidence(duv=candidate)

    def test_unregistered_evidence_host_rejected(self):
        for candidate in (
            "https://www.portosdoparana.pr.gov.br.evil.example/f.pdf",
            "https://notregistered.example/f.pdf",
            "https://user:pass@www.portosdoparana.pr.gov.br/f.pdf",
            "http://www.portosdoparana.pr.gov.br/f.pdf",
            "https://www.portosdoparana.pr.gov.br:444/f.pdf",
        ):
            with self.subTest(url=candidate):
                with self.assertRaisesRegex(ValueError, "association evidence URL"):
                    evidence(link_evidence_url=candidate)

    def test_external_psp_document_candidate_is_allowed_but_not_approved(self):
        item = evidence(
            link_evidence_url="https://concentrador.portosempapel.gov.br/portal/test",
            link_document_sha256="b"*64,
            evidence_kind="OFFICIAL_AUTHORITY_CROSSWALK",
        )
        self.assertEqual(review(records=[item]).status,
                         "CANDIDATE_READY_FOR_EXTERNAL_VERIFICATION")

    def test_psp_host_cannot_pretend_to_be_original_pdf_pair(self):
        with self.assertRaisesRegex(ValueError, "original PDF pair requires port authority"):
            evidence(
                link_evidence_url="https://concentrador.portosempapel.gov.br/portal/test")

    def test_original_pdf_pair_requires_exact_document_url(self):
        result = review(records=[evidence(
            link_evidence_url="https://www.portosdoparana.pr.gov.br/official/other.pdf")])
        self.assertIn("ORIGINAL_PDF_URL_MISMATCH", result.rejected_reasons)

    def test_original_pdf_must_really_show_both_ids(self):
        snap = replace(edition(), rows=(
            replace(programme(), explicit_duv=None),
        ), excluded_call_rows=1)
        result = review(snapshot=snap)
        self.assertIn("ORIGINAL_PDF_DOES_NOT_DECLARE_PAIR", result.rejected_reasons)
        self.assertEqual(result.candidate_pairs, ())

    def test_external_direct_evidence_may_link_pdf_without_duv_but_stays_candidate(self):
        snap = replace(edition(), rows=(
            replace(programme(), explicit_duv=None),
        ), excluded_call_rows=1)
        independent = evidence(
            link_evidence_url="https://concentrador.portosempapel.gov.br/portal/association",
            link_document_sha256="b" * 64,
            evidence_kind="OFFICIAL_AUTHORITY_CROSSWALK",
        )
        result = review(snapshot=snap, records=[independent])
        self.assertEqual(result.status, "CANDIDATE_READY_FOR_EXTERNAL_VERIFICATION")
        self.assertFalse(result.canonical_duv_link_allowed)

    def test_original_pdf_pair_requires_same_hash(self):
        with self.assertRaisesRegex(ValueError, "hash does not match"):
            evidence(link_document_sha256="b"*64)

    def test_invalid_document_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, "two original document hashes"):
            evidence(link_document_sha256="bad")

    def test_review_cannot_precede_acquisition(self):
        with self.assertRaisesRegex(ValueError, "temporal order invalid"):
            evidence(reviewed_at="2026-10-20T11:00:00+00:00")

    def test_acquisition_cannot_precede_link_publication(self):
        with self.assertRaisesRegex(ValueError, "temporal order invalid"):
            evidence(published_at="2026-10-20T13:00:00+00:00")

    def test_naive_timestamps_fail(self):
        with self.assertRaises(ValueError):
            evidence(reviewed_at="2026-10-20T13:00:00")
        with self.assertRaises(ValueError):
            review(at="2026-10-20T14:00:00")

    def test_unverified_evidence_kind_rejected(self):
        with self.assertRaisesRegex(ValueError, "direct documentary evidence"):
            evidence(evidence_kind="INFERRED_FROM_VESSEL_NAME")

    def test_missing_independent_review_and_evidence_proofs_rejected(self):
        for field in ("reviewed_by", "link_evidence_id", "acquisition_evidence_id",
                      "publication_evidence_id"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "IDs required"):
                    evidence(**{field: ""})

    def test_itaqui_programme_cannot_enter_crosswalk(self):
        snap = edition()
        bad = replace(snap, port_id="ITAQUI", series=None,
            source_url="https://www.portodoitaqui.com/other.pdf",
            rows=(replace(programme(), programme_number=None),))
        with self.assertRaisesRegex(ValueError, "requires Paranagua"):
            review(snapshot=bad)

    def test_all_candidates_with_one_out_of_scope_fail_closed(self):
        result = review(records=[evidence(), evidence(source_id="FOREIGN")])
        self.assertIn("DOCUMENT_SCOPE_MISMATCH", result.rejected_reasons)
        self.assertEqual(result.candidate_pairs, ())

    def test_source_row_not_unique_is_a_programme_line_group_not_two_visits(self):
        snap = replace(edition(), source_rows=2,
                       rows=(programme(), replace(programme(), source_row=2,
                              product="MILHO")), excluded_call_rows=2)
        result = review(snapshot=snap)
        self.assertEqual(len(result.candidate_pairs), 1)
        self.assertFalse(result.summary()["canonical_duv_link_allowed"])

    def test_non_typed_evidence_rejected(self):
        with self.assertRaises(TypeError):
            assess_programme_duv_evidence(edition(), ["hello"], as_of="2026-10-20T15:00:00+00:00")

    def test_input_edition_is_not_mutated(self):
        before = edition()
        initial = repr(before)
        review(snapshot=before)
        self.assertEqual(repr(before), initial)


if __name__ == "__main__":
    unittest.main()
