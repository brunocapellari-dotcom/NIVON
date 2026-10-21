"""Synthetic, offline tests for *pre*-homologation evidence. No real rights granted."""
import hashlib
import unittest
from dataclasses import replace

from nivon.maritime.lineup_history import LineupVintage
from nivon.maritime.lineup_homologation import (
    PILOT_PORTS, EditionEvidence, OperationRights, PilotSource,
    audit_edition, audit_pilot_portfolio, audit_source,
)
from nivon.maritime.shipping_reconciliation import LineupCall


CUTOFF = "2026-10-21T11:00:00+00:00"
HOSTS = {
    "SANTOS": "www.portodesantos.com.br",
    "PARANAGUA": "www.portosdoparana.pr.gov.br",
    "ITAQUI": "www.portodoitaqui.com",
    "SANTAREM": "www.cdp.com.br",
    "BARCARENA_VILA_DO_CONDE": "www.cdp.com.br",
}
MODES = {
    "SANTOS": "HTML_SANTOS_SCHEDULE",
    "PARANAGUA": "PDF_PARANAGUA",
    "ITAQUI": "PDF_ITAQUI",
    "SANTAREM": "HTML_CDP_BERTH_TABLE",
    "BARCARENA_VILA_DO_CONDE": "HTML_CDP_BERTH_TABLE",
}


def plan(port="SANTOS"):
    return PilotSource(
        port_id=port, source_id="OFFICIAL_" + port,
        mode=MODES[port],
        registered_url=(f"https://{HOSTS[port]}/official/" if MODES[port].startswith("PDF")
                        else f"https://{HOSTS[port]}/official/lineup"),
        series="EXPORT_OESTE" if port == "PARANAGUA" else None,
    )


def edition(target=None, num=1, *, document=None, **changes):
    target = target or plan()
    stamp = f"2026-10-20T{num+10:02d}:00:00+00:00"
    published = f"2026-10-20T{num+9:02d}:30:00+00:00"
    is_pdf = target.mode.startswith("PDF")
    raw = document if document is not None else (
        (b"%PDF-1.4\n1 0 obj\n" if is_pdf else b"<html><body>")
        + str(num).encode("utf-8")
    )
    mime = "application/pdf" if is_pdf else "text/html"
    v = LineupVintage(
        port_id=target.port_id, source_id=target.source_id,
        source_sha256=hashlib.sha256(raw).hexdigest(), collected_at=stamp,
        published_at=published, publication_evidence_id=f"PUB_{num}",
        reference_date="2026-10-20", competence="2026-10",
        calls=(LineupCall(
            call_id=f"{target.port_id}:{target.source_id}:DUV-{num}",
            port_id=target.port_id, source_id=target.source_id,
            vessel_name="TEST VESSEL", imo="9074729",
            eta="2026-10-22T10:00:00+00:00",
            collected_at=stamp, planned_volume_t=23000.0,
        ),),
    )
    fields = dict(vintage=v, document_bytes=raw, mime=mime,
        source_url=(target.registered_url + f"test-{num}"
                    if target.mode.startswith("PDF") else target.registered_url),
        parser_mode=target.mode, series=target.series, eligible_source_rows=1,
        rejected_eligible_rows=0, parser_review_id="parser-review",
        identity_review_id="duv-review", acquisition_evidence_id="acquisition-proof",
        evidence_kind="OFFICIAL_CANDIDATE")
    fields.update(changes)
    return EditionEvidence(**fields)


def rights(target=None, **changes):
    target = target or plan()
    fields = dict(
        port_id=target.port_id, source_id=target.source_id,
        operations=frozenset({"COLLECT", "STORE", "INTERNAL_ANALYSIS"}),
        evidence_id="signed-licensing-record",
        reviewed_by="independent-legal-reviewer",
        checked_at="2026-10-19T10:00:00+00:00",
        status="VERIFIED",
    )
    fields.update(changes)
    return OperationRights(**fields)


def source(target=None, *, rows=None, licenses=None, at=CUTOFF):
    target = target or plan()
    rows = rows if rows is not None else [edition(target, num) for num in (1, 2, 3)]
    licenses = licenses if licenses is not None else [rights(target)]
    return audit_source(target, rows, licenses, as_of=at)


class HomologationManifestTests(unittest.TestCase):
    def test_no_supplied_editions_is_blocked(self):
        record = source(rows=[], licenses=[])
        self.assertEqual(record.status, "BLOCKED")
        self.assertIn("RIGHTS_RECORD_MISSING", record.blockers)
        self.assertIn("INSUFFICIENT_INDEPENDENT_EDITIONS", record.blockers)
        self.assertFalse(record.release_allowed)

    def test_three_distinct_reviewed_editions_reach_review_not_release(self):
        record = source()
        self.assertEqual(record.status, "READY_FOR_INDEPENDENT_REVIEW")
        self.assertEqual(record.valid_editions, 3)
        self.assertFalse(record.release_allowed)
        self.assertFalse(record.to_dict()["release_allowed"])

    def test_two_editions_do_not_pass(self):
        record = source(rows=[edition(num=1), edition(num=2)])
        self.assertIn("INSUFFICIENT_INDEPENDENT_EDITIONS", record.blockers)

    def test_cannot_override_min_three(self):
        with self.assertRaises(ValueError):
            audit_source(plan(), [edition()], [rights()], as_of=CUTOFF, min_editions=1)

    def test_reused_identical_document_does_not_pass(self):
        duplicate_document = edition(num=1).document_bytes
        record = source(rows=[edition(num=1), edition(num=2, document=duplicate_document), edition(num=3)])
        self.assertIn("REUSED_DOCUMENT_ACROSS_EDITIONS", record.blockers)

    def test_same_collection_time_rejected(self):
        first = edition()
        duplicate = replace(first, document_bytes=first.document_bytes + b"repeat")
        duplicate_v = replace(duplicate.vintage, source_sha256=hashlib.sha256(duplicate.document_bytes).hexdigest())
        duplicate = replace(duplicate, vintage=duplicate_v)
        record = source(rows=[first, duplicate, edition(num=2), edition(num=3)])
        self.assertIn("DUPLICATE_COLLECTION_INSTANT", record.blockers)

    def test_wrong_document_hash_rejected(self):
        wrong = replace(edition(), document_bytes=b"<html>tampered</html>")
        self.assertIn("DOCUMENT_HASH_MISMATCH", audit_edition(wrong, plan()))

    def test_wrong_port_authority_url_rejected(self):
        wrong = replace(edition(), source_url="https://www.cdp.com.br/example")
        self.assertIn("UNVERIFIED_OFFICIAL_URL", audit_edition(wrong, plan()))

    def test_https_url_with_embedded_credentials_or_custom_port_blocked(self):
        for url in ("http://www.portodesantos.com.br/snapshot",
                    "https://u:p@www.portodesantos.com.br/snapshot",
                    "https://www.portodesantos.com.br:444/snapshot",
                    "https://www.portodesantos.com.br/snapshot#redirect",
                    "https://www.portodesantos.com.br.evil.example/snapshot"):
            with self.subTest(url=url):
                bad = replace(edition(), source_url=url)
                self.assertIn("UNVERIFIED_OFFICIAL_URL", audit_edition(bad, plan()))

    def test_unregistered_page_on_same_official_domain_blocked(self):
        wrong = replace(edition(), source_url="https://www.portodesantos.com.br/official/other")
        self.assertIn("URL_NOT_REGISTERED_FOR_SOURCE", audit_edition(wrong, plan()))

    def test_unregistered_pdf_directory_blocked(self):
        p = plan("ITAQUI")
        wrong = replace(edition(p), source_url="https://www.portodoitaqui.com/unrelated/test.pdf")
        self.assertIn("URL_NOT_REGISTERED_FOR_SOURCE", audit_edition(wrong, p))

    def test_registered_url_path_traversal_rejected(self):
        p = plan("ITAQUI")
        bad = replace(edition(p), source_url=p.registered_url + "../unrelated.pdf")
        self.assertIn("UNVERIFIED_OFFICIAL_URL", audit_edition(bad, p))

    def test_registered_pdf_prefix_requires_trailing_slash(self):
        with self.assertRaisesRegex(ValueError, "end in slash"):
            PilotSource("ITAQUI", "SOURCE", MODES["ITAQUI"],
                        "https://www.portodoitaqui.com/official")

    def test_registered_html_url_cannot_use_unspecific_root(self):
        with self.assertRaisesRegex(ValueError, "exact document"):
            PilotSource("SANTOS", "SOURCE", MODES["SANTOS"],
                        "https://www.portodesantos.com.br/")

    def test_pdf_signature_wrong_blocked(self):
        p = plan("ITAQUI")
        bad = replace(edition(p), document_bytes=b"not a pdf")
        self.assertIn("PDF_MIME_SIGNATURE_MISMATCH", audit_edition(bad, p))

    def test_html_signature_wrong_blocked(self):
        bad = replace(edition(), mime="application/pdf")
        self.assertIn("HTML_MIME_SIGNATURE_MISMATCH", audit_edition(bad, plan()))

    def test_missing_publication_evidence_blocks(self):
        row = edition()
        unproven = replace(row, vintage=replace(row.vintage, published_at=None, publication_evidence_id=None))
        self.assertIn("PUBLICATION_UNPROVEN", audit_edition(unproven, plan()))

    def test_future_evidence_cannot_be_used_at_past_cutoff(self):
        record = source(at="2026-10-20T10:00:00+00:00")
        self.assertIn("FUTURE_EVIDENCE_IN_AUDIT", record.blockers)
        self.assertEqual(record.valid_editions, 0)

    def test_missing_parser_review_fails_closed(self):
        bad = replace(edition(), parser_review_id=None)
        self.assertIn("PARSER_NOT_REVIEWED", audit_edition(bad, plan()))

    def test_missing_identity_review_fails_closed(self):
        bad = replace(edition(), identity_review_id="")
        self.assertIn("CALL_IDENTITY_NOT_REVIEWED", audit_edition(bad, plan()))

    def test_missing_acquisition_proof_fails_closed(self):
        bad = replace(edition(), acquisition_evidence_id="")
        self.assertIn("ACQUISITION_UNPROVEN", audit_edition(bad, plan()))

    def test_fixtures_never_count_as_official_candidate(self):
        fixture = replace(edition(), evidence_kind="SYNTHETIC")
        self.assertIn("NOT_REAL_OFFICIAL_CANDIDATE", audit_edition(fixture, plan()))

    def test_partial_or_bad_row_accounting_blocked(self):
        for field in (
            {"eligible_source_rows": 2, "rejected_eligible_rows": 0},
            {"eligible_source_rows": 2, "rejected_eligible_rows": 1},
            {"eligible_source_rows": True},
            {"eligible_source_rows": 0},
        ):
            with self.subTest(fields=field):
                bad = replace(edition(), **field)
                self.assertTrue(audit_edition(bad, plan()))

    def test_cross_port_vintage_does_not_satisfy_other_plan(self):
        p = plan("PARANAGUA")
        record = source(rows=[edition(p, num) for num in (1, 2, 3)])
        self.assertIn("SOURCE_SCOPE_MISMATCH", record.blockers)

    def test_missing_verification_of_rights_blocks(self):
        record = source(licenses=[rights(status="PENDING")])
        self.assertIn("RIGHTS_NOT_VERIFIED_OR_EXPIRED", record.blockers)

    def test_unlicensed_operation_is_blocked(self):
        record = source(licenses=[rights(operations=frozenset({"COLLECT", "STORE"}))])
        self.assertIn("RIGHTS_INTERNAL_ANALYSIS_MISSING", record.blockers)

    def test_expired_rights_are_blocked(self):
        record = source(licenses=[rights(expires_at="2026-10-20T23:00:00+00:00")])
        self.assertIn("RIGHTS_NOT_VERIFIED_OR_EXPIRED", record.blockers)

    def test_different_port_rights_not_reused(self):
        record = source(licenses=[rights(plan("ITAQUI"))])
        self.assertIn("RIGHTS_RECORD_MISSING", record.blockers)

    def test_external_review_must_be_prior_to_audit(self):
        record = source(licenses=[rights(checked_at="2026-10-22T10:00:00+00:00")])
        self.assertIn("RIGHTS_NOT_VERIFIED_OR_EXPIRED", record.blockers)

    def test_rights_publication_permission_never_opens_release_here(self):
        record = source(licenses=[rights(operations=frozenset({
            "COLLECT", "STORE", "INTERNAL_ANALYSIS", "PUBLISH", "REDISTRIBUTE", "BACKUP"
        }))])
        self.assertEqual(record.status, "READY_FOR_INDEPENDENT_REVIEW")
        self.assertFalse(record.release_allowed)

    def test_paranagua_requires_explicit_series(self):
        with self.assertRaisesRegex(ValueError, "canonical series"):
            PilotSource("PARANAGUA", "PARANAGUA_SOURCE", MODES["PARANAGUA"],
                        "https://www.portosdoparana.pr.gov.br/official/")
        with self.assertRaisesRegex(ValueError, "series only"):
            PilotSource("ITAQUI", "ITAQUI_SOURCE", MODES["ITAQUI"],
                        "https://www.portodoitaqui.com/official/", series="EXPORT_OESTE")

    def test_parser_mismatch_fails(self):
        row = replace(edition(), parser_mode="PDF_ITAQUI")
        self.assertIn("PARSER_CONTRACT_MISMATCH", audit_edition(row, plan()))

    def test_five_pilot_portfolio_is_not_approved_even_with_all_files(self):
        plans = [plan(port) for port in sorted(PILOT_PORTS)]
        rows = [edition(p, num) for p in plans for num in (1, 2, 3)]
        decisions = [rights(p) for p in plans]
        record = audit_pilot_portfolio(plans, rows, decisions, as_of=CUTOFF)
        self.assertEqual(record.missing_pilot_ports, ())
        self.assertEqual(record.status, "READY_FOR_INDEPENDENT_REVIEW")
        self.assertEqual(len(record.sources), 5)
        self.assertFalse(record.release_allowed)
        self.assertFalse(record.to_dict()["release_allowed"])

    def test_missing_pilot_port_always_blocks_portfolio(self):
        plans = [plan(port) for port in sorted(PILOT_PORTS - {"ITAQUI"})]
        rows = [edition(p, num) for p in plans for num in (1, 2, 3)]
        record = audit_pilot_portfolio(plans, rows, [rights(p) for p in plans], as_of=CUTOFF)
        self.assertEqual(record.status, "BLOCKED")
        self.assertEqual(record.missing_pilot_ports, ("ITAQUI",))

    def test_duplicate_pilot_plan_is_error(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit_pilot_portfolio([plan(), plan()], [], [], as_of=CUTOFF)


if __name__ == "__main__":
    unittest.main()
