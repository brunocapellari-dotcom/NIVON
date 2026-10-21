"""Actual PDF byte -> pdfplumber -> parser -> port-call bridge contract tests.

These PDFs are generated in memory from wholly synthetic tables with ReportLab.
They are NOT real port-authority documents, licensed source evidence or an
assertion that current Itaqui/Paranagua layouts match these fixtures.

This module remains skipped in the lightweight no-dependencies CI job;
the maritime-pdf-extraction job installs pinned test-only libraries and
explicitly executes every test in this module.
"""
from __future__ import annotations

import hashlib
import io
import unittest
from datetime import date

from nivon.coleta_web import FonteWeb
from nivon.portos_automaticos import ContratoPorto, ErroPorto, processar_documento_porto
from nivon.maritime.official_lineup_bridge import bridge_official_pdf_document
from nivon.maritime.lineup_history import vintage_from_official_bridge
from nivon.maritime.maritime_store import MaritimeStore
from nivon.maritime.pdf_programme_ledger import (
    PdfProgrammeLedger, edition_from_pdf_bridge,
)

try:
    import pdfplumber
    from reportlab.pdfgen import canvas
except ImportError:
    pdfplumber = None
    canvas = None


URLS = {
    "ITAQUI": "https://www.portodoitaqui.com/fixture/lineup.pdf",
    "PARANAGUA": "https://www.portosdoparana.pr.gov.br/fixture/lineup.pdf",
}
STAMP = "2026-10-20T12:00:00+00:00"


def synthetic_table_pdf(headers, data_rows, col_widths, *, preamble=None):
    """Build fully valid PDF geometry with explicit ruled cells, no network."""
    if canvas is None:
        raise RuntimeError("reportlab unavailable")
    rows = ([preamble] if preamble is not None else []) + [headers] + list(data_rows)
    if any(len(row) != len(col_widths) for row in rows):
        raise ValueError("invalid fixture columns")
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, pagesize=(1000, 600), pageCompression=0)
    x_positions = [24.0]
    for width in col_widths:
        x_positions.append(x_positions[-1] + width)
    top = 540.0
    row_height = 31.0
    page.setLineWidth(0.7)
    for idx in range(len(rows) + 1):
        y = top - idx * row_height
        page.line(x_positions[0], y, x_positions[-1], y)
    for x in x_positions:
        page.line(x, top, x, top - len(rows) * row_height)
    page.setFont("Helvetica", 9)
    for i, row in enumerate(rows):
        y = top - (i + 0.65) * row_height
        for j, value in enumerate(row):
            page.drawString(x_positions[j] + 4, y, str(value))
    page.showPage()
    page.save()
    payload = buffer.getvalue()
    if not payload.startswith(b"%PDF-"):
        raise AssertionError("fixture was not a real PDF file")
    return payload


def itaqui_pdf(*, duv="DUV-I-001", eta="21/10/2026 09:00", status="ESPERADO"):
    return synthetic_table_pdf(
        ("Berco", "Status", "IMO", "Navio", "Produto", "Qtde", "Prev. Chegada", "DUV"),
        (("BERCO 1", status, "9074729", "NAVIO TESTE", "SOJA", "15000,00", eta, duv),),
        (80, 85, 70, 125, 75, 80, 145, 80),
    )


def paranagua_pdf(*, duv="DUV-P-001", arrival="21/10/2026",
                  clock="09:00", prog="PRG-5"):
    return synthetic_table_pdf(
        ("Navio", "N. Prog", "Chegada", "Hora", "Berco", "DUV", "Soja"),
        (("NAVIO TESTE", prog, arrival, clock, "BERCO 2", duv, "23000,00"),),
        (160, 85, 115, 70, 90, 120, 100),
        preamble=("LINE-UP CORREDOR OESTE", "", "", "", "", "", ""),
    )


def contract(port, *, approved=True):
    return ContratoPorto(
        porto=port,
        modo="PDF_ITAQUI" if port == "ITAQUI" else "PDF_PARANAGUA",
        data_referencia=date(2026, 10, 20),
        serie="EXPORT_OESTE" if port == "PARANAGUA" else None,
        fonte=FonteWeb(
            fonte_id="FIXTURE_" + port, url=URLS[port],
            dominio_autorizado=URLS[port].split("/")[2], formato="PDF",
            status_direitos="APROVADA" if approved else "PENDENTE",
            operacoes_permitidas=frozenset({"COLETA"}) if approved else frozenset(),
        ),
    )


def document(port, payload):
    return {
        "conteudo": payload,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload), "mime": "application/pdf",
        "fonte_id": "FIXTURE_" + port, "url": URLS[port],
        "capturado_em": STAMP,
    }


@unittest.skipUnless(canvas is not None and pdfplumber is not None,
                     "PDF E2E libraries installed only in dedicated CI job")
class PdfPlumberE2ETests(unittest.TestCase):
    def test_itaqui_pdf_bytes_reach_programmed_call_with_precise_eta(self):
        payload = itaqui_pdf()
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            extracted = pdf.pages[0].extract_tables()
        self.assertEqual(extracted[0][0][7], "DUV")
        result = bridge_official_pdf_document(
            contract=contract("ITAQUI"), document=document("ITAQUI", payload))
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].eta, "2026-10-21T12:00:00+00:00")
        self.assertEqual(result.candidates[0].planned_volume_t, 15000.0)
        self.assertEqual(result.candidates[0].lineup_status, "PROGRAMMED")
        self.assertFalse(result.publication_allowed)

    def test_paranagua_split_date_and_clock_reconstructed_only_when_explicit(self):
        payload = paranagua_pdf()
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            extracted = pdf.pages[0].extract_tables()
        self.assertEqual(extracted[0][1][2:4], ["Chegada", "Hora"])
        result = bridge_official_pdf_document(
            contract=contract("PARANAGUA"), document=document("PARANAGUA", payload))
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].eta, "2026-10-21T12:00:00+00:00")
        self.assertTrue(result.candidates[0].call_id.endswith(":DUV-P-001"))
        self.assertNotIn("PRG-5", result.candidates[0].call_id)
        self.assertEqual(result.pdf_program_rows[0].programme_number, "EXPORT_OESTE:PRG-5")
        self.assertTrue(result.pdf_program_rows[0].eta_fully_declared)
        self.assertEqual(result.pdf_program_rows[0].evidence_class, "PROGRAMME_REFERENCE_NOT_PORT_CALL")

    def test_itaqui_real_pdf_date_only_kept_as_invalid_evidence(self):
        payload = itaqui_pdf(eta="21/10/2026")
        result = bridge_official_pdf_document(
            contract=contract("ITAQUI"), document=document("ITAQUI", payload))
        self.assertEqual(result.source_rows, 1)
        self.assertFalse(result.candidates)
        self.assertEqual(result.excluded[0]["reason"], "precise_pdf_eta_missing_or_invalid")

    def test_paranagua_real_pdf_date_without_clock_not_fabricated(self):
        payload = paranagua_pdf(clock="")
        result = bridge_official_pdf_document(
            contract=contract("PARANAGUA"), document=document("PARANAGUA", payload))
        self.assertEqual(result.source_rows, 1)
        self.assertFalse(result.candidates)
        self.assertEqual(result.excluded[0]["reason"], "precise_pdf_eta_missing_or_invalid")

    def test_paranagua_n_prog_without_duv_stays_unidentified(self):
        payload = paranagua_pdf(duv="", prog="PRG-555")
        result = bridge_official_pdf_document(
            contract=contract("PARANAGUA"), document=document("PARANAGUA", payload))
        self.assertEqual(result.source_rows, 1)
        self.assertFalse(result.candidates)
        self.assertEqual(result.excluded[0]["reason"], "explicit_duv_missing_or_invalid")
        self.assertEqual(result.pdf_program_rows[0].programme_number, "EXPORT_OESTE:PRG-555")
        self.assertIsNone(result.pdf_program_rows[0].explicit_duv)
        self.assertFalse(result.summary()["programme_references_are_verified_port_calls"])
        with self.assertRaisesRegex(ValueError, "partial lineup"):
            vintage_from_official_bridge(result, reference_date="2026-10-20",
                competence="2026-10", published_at="2026-10-20T11:00:00+00:00",
                publication_evidence_id="SYNTHETIC_ONLY")

    def test_paranagua_pdf_without_duv_replays_as_programming_only(self):
        payload = paranagua_pdf(duv="", prog="PRG-500")
        checked = bridge_official_pdf_document(
            contract=contract("PARANAGUA"), document=document("PARANAGUA", payload))
        self.assertEqual(checked.candidates, ())
        self.assertEqual(checked.pdf_program_rows[0].programme_number, "EXPORT_OESTE:PRG-500")
        version = edition_from_pdf_bridge(
            checked, reference_date="2026-10-20", competence="2026-10",
            published_at="2026-10-20T11:00:00+00:00",
            publication_evidence_id="SYNTHETIC_PUBLICATION_PROOF",
        )
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            self.assertTrue(ledger.save(version, storage_authorized=True))
            found = ledger.select_asof(
                port_id="PARANAGUA", source_id="FIXTURE_PARANAGUA",
                series="EXPORT_OESTE", as_of="2026-10-20T12:30:00+00:00",
                read_authorized=True)
            self.assertEqual(found.summary()["programme_numbers_declared"], 1)
            self.assertEqual(found.summary()["rows_not_mappable_to_duv"], 1)
            self.assertIsNone(found.summary()["verified_port_call_count"])
            self.assertFalse(found.summary()["publication_allowed"])

    def test_itaqui_pdf_without_duv_replays_without_programme_number(self):
        payload = itaqui_pdf(duv="")
        checked = bridge_official_pdf_document(
            contract=contract("ITAQUI"), document=document("ITAQUI", payload))
        self.assertEqual(checked.candidates, ())
        version = edition_from_pdf_bridge(
            checked, reference_date="2026-10-20", competence="2026-10",
            published_at="2026-10-20T11:00:00+00:00",
            publication_evidence_id="SYNTHETIC_PUBLICATION_PROOF",
        )
        with MaritimeStore() as store:
            ledger = PdfProgrammeLedger(store)
            ledger.save(version, storage_authorized=True)
            result = ledger.select_asof(
                port_id="ITAQUI", source_id="FIXTURE_ITAQUI", series=None,
                as_of="2026-10-20T12:30:00+00:00", read_authorized=True)
            self.assertEqual(result.summary()["programme_pdf_rows"], 1)
            self.assertEqual(result.summary()["programme_numbers_declared"], 0)
            self.assertIsNone(result.summary()["verified_port_call_count"])

    def test_itaqui_physical_status_never_promoted_to_schedule(self):
        payload = itaqui_pdf(status="ATRACADO")
        with self.assertRaises(ErroPorto):
            processar_documento_porto(contract("ITAQUI"), document("ITAQUI", payload))

    def test_tampered_pdf_detected_before_pdfplumber_parse(self):
        payload = itaqui_pdf()
        record = document("ITAQUI", payload)
        record["conteudo"] = payload + b"altered"
        with self.assertRaisesRegex(ErroPorto, "SHA-256 divergente"):
            bridge_official_pdf_document(contract=contract("ITAQUI"), document=record)

    def test_no_rights_raises_before_pdfplumber_parse(self):
        payload = itaqui_pdf()
        with self.assertRaises(PermissionError):
            bridge_official_pdf_document(
                contract=contract("ITAQUI", approved=False),
                document=document("ITAQUI", payload),
            )

    def test_pdf_extraction_and_vintage_requires_external_publication_proof(self):
        payload = paranagua_pdf()
        result = bridge_official_pdf_document(
            contract=contract("PARANAGUA"), document=document("PARANAGUA", payload))
        vintage = vintage_from_official_bridge(
            result, reference_date="2026-10-20", competence="2026-10",
        )
        self.assertIsNone(vintage.published_utc)
        self.assertEqual(vintage.source_sha256, hashlib.sha256(payload).hexdigest())
        self.assertFalse(result.realized_cargo_claimed)


if __name__ == "__main__":
    unittest.main()
