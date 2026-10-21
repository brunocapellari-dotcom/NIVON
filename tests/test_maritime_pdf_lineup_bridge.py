"""Offline PDF-table regression: supplied bytes and MOCKED extracted tables only.

These are not official PDFs and do not homologate parser layouts or rights.
"""
from contextlib import contextmanager
from datetime import date
import hashlib
import unittest
from unittest.mock import patch

from nivon._agrolog_portos_pdf import PdfTable, parse_itaqui_tables, parse_paranagua_tables
from nivon.coleta_web import FonteWeb
from nivon.portos_automaticos import ContratoPorto, ErroPorto
from nivon.maritime.official_lineup_bridge import bridge_official_pdf_document
from nivon.maritime.lineup_history import vintage_from_official_bridge

STAMP = "2026-10-20T12:00:00Z"
URLS = {
    "ITAQUI": "https://www.portodoitaqui.com/documentos/lineup.pdf",
    "PARANAGUA": "https://www.portosdoparana.pr.gov.br/documentos/lineup.pdf",
}


def contract(port="ITAQUI", *, granted=True):
    url = URLS[port]
    return ContratoPorto(
        porto=port, modo="PDF_ITAQUI" if port == "ITAQUI" else "PDF_PARANAGUA",
        data_referencia=date(2026, 10, 20),
        serie="EXPORT_OESTE" if port == "PARANAGUA" else None,
        fonte=FonteWeb(
            fonte_id="OFFICIAL_" + port + "_TEST",
            url=url, dominio_autorizado=url.split("/")[2], formato="PDF",
            status_direitos="APROVADA" if granted else "PENDENTE",
            operacoes_permitidas=frozenset({"COLETA"}) if granted else frozenset(),
        ),
    )


def document(port="ITAQUI", *, stamp=STAMP):
    raw = b"%PDF-1.4\nSYNTHETIC NOT REAL PDF"
    return {
        "conteudo": raw, "sha256": hashlib.sha256(raw).hexdigest(),
        "mime": "application/pdf", "url": URLS[port],
        "fonte_id": "OFFICIAL_" + port + "_TEST",
        "capturado_em": stamp, "bytes": len(raw),
    }


def itaqui(*, duv="DUV-I-11", eta="21/10/2026 09:00", status="ESPERADO", vessel="NAVIO TESTE"):
    return ("BERÇO 1", status, "9074729", vessel, "SOJA", "15.000,00", eta, duv)


def tables_itaqui(*rows):
    headers = ("Berço", "Status", "IMO", "Navio", "Produto", "Qtde", "Prev. Chegada", "DUV")
    return (PdfTable(page_number=1, rows=(headers, *rows)),)


def paranagua(*, duv="DUV-P-11", eta="21/10/2026 09:00", prog="PRG-5",
              vessel="NAVIO TESTE", volume="23.000,00"):
    return (vessel, prog, eta, "BERÇO 2", duv, volume)


def tables_paranagua(*rows):
    return (PdfTable(page_number=1, rows=(
        ("LINE-UP CORREDOR OESTE", "", "", "", "", ""),
        ("Navio", "N. Prog", "Chegada", "Berço", "DUV", "Soja"),
        *rows,
    )),)


@contextmanager
def mocked_tables(tables, *, bridge_tables=None):
    with patch("nivon.portos_automaticos.extract_pdf_tables", return_value=list(tables)):
        with patch("nivon.maritime.official_lineup_bridge.extract_pdf_tables",
                   return_value=list(bridge_tables if bridge_tables is not None else tables)):
            yield


def bridge(port, tables, **kw):
    with mocked_tables(tables):
        return bridge_official_pdf_document(contract=contract(port), document=document(port), **kw)


class MaritimePdfBridgeTests(unittest.TestCase):
    def test_itaqui_explicit_duv_and_full_eta_create_programming_not_realization(self):
        result = bridge("ITAQUI", tables_itaqui(itaqui()))
        self.assertEqual(result.source_rows, 1)
        self.assertEqual(len(result.candidates), 1)
        self.assertFalse(result.excluded)
        call = result.candidates[0]
        self.assertEqual(call.call_id, "ITAQUI:OFFICIAL_ITAQUI_TEST:DUV-I-11")
        self.assertEqual(call.eta, "2026-10-21T12:00:00+00:00")
        self.assertEqual(call.planned_volume_t, 15000.0)
        self.assertEqual(call.lineup_status, "PROGRAMMED")
        self.assertFalse(result.realized_cargo_claimed)
        self.assertFalse(result.publication_allowed)

    def test_itaqui_anchored_and_berth_status_never_counted_as_schedule(self):
        result = bridge("ITAQUI", tables_itaqui(
            itaqui(status="ATRACADO", vessel="OPERANDO", duv="DUV-1"),
            itaqui(status="FUNDEADO", vessel="WAITING", duv="DUV-2"),
            itaqui(status="ESPERADO", vessel="SCHEDULED", duv="DUV-3"),
        ))
        self.assertEqual(result.source_rows, 1)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].vessel_name, "SCHEDULED")

    def test_itaqui_no_duv_blocks_verified_vintage(self):
        result = bridge("ITAQUI", tables_itaqui(itaqui(duv="")))
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.excluded[0]["reason"], "explicit_duv_missing_or_invalid")
        with self.assertRaisesRegex(ValueError, "partial lineup"):
            vintage_from_official_bridge(result, reference_date="2026-10-20",
                competence="2026-10", published_at="2026-10-20T11:00:00Z",
                publication_evidence_id="SYNTHETIC_PROOF")

    def test_paranagua_program_number_is_not_duv(self):
        raw = tables_paranagua(paranagua(duv="", prog="PRG-445"))
        parsed = parse_paranagua_tables(raw, reference_date=date(2026, 10, 20),
                                        series="EXPORT_OESTE")
        self.assertIn("EXPORT_OESTE:PRG-445", parsed[0]["call_id"])
        self.assertEqual(parsed[0]["duv"], "")
        result = bridge("PARANAGUA", raw)
        self.assertFalse(result.candidates)
        self.assertEqual(result.excluded[0]["reason"], "explicit_duv_missing_or_invalid")

    def test_itaqui_duvida_column_must_not_be_mistaken_for_duv(self):
        raw = tables_itaqui(itaqui())
        bad = (PdfTable(page_number=1, rows=(
            tuple("Dúvida" if cell == "DUV" else cell for cell in raw[0].rows[0]),
            *raw[0].rows[1:],
        )),)
        result = bridge("ITAQUI", bad)
        self.assertFalse(result.candidates)
        self.assertEqual(result.excluded[0]["reason"], "explicit_duv_missing_or_invalid")

    def test_paranagua_unverified_similar_duv_column_rejected(self):
        raw = tables_paranagua(paranagua())
        headers = tuple("Observação DUV" if c == "DUV" else c for c in raw[0].rows[1])
        bad = (PdfTable(page_number=1, rows=(raw[0].rows[0], headers, *raw[0].rows[2:])),)
        result = bridge("PARANAGUA", bad)
        self.assertFalse(result.candidates)
        self.assertEqual(result.excluded[0]["reason"], "explicit_duv_missing_or_invalid")

    def test_paranagua_explicit_duv_can_become_programmed_port_call(self):
        result = bridge("PARANAGUA", tables_paranagua(paranagua()))
        self.assertEqual(len(result.candidates), 1)
        self.assertTrue(result.candidates[0].call_id.endswith(":DUV-P-11"))
        self.assertNotIn("PRG-5", result.candidates[0].call_id)
        self.assertEqual(result.candidates[0].planned_volume_t, 23000.0)

    def test_valid_pdf_bridge_can_form_internal_asof_vintage_only(self):
        result = bridge("PARANAGUA", tables_paranagua(paranagua()))
        vintage = vintage_from_official_bridge(
            result, reference_date="2026-10-20", competence="2026-10",
            published_at="2026-10-20T11:00:00Z", publication_evidence_id="SYNTHETIC_PROOF")
        self.assertEqual(len(vintage.calls), 1)
        self.assertEqual(vintage.source_sha256, document("PARANAGUA")["sha256"])
        self.assertEqual(vintage.provenance()["evidence_class"], "LINEUP_DECLARED_NOT_REALIZED")

    def test_duplicate_duv_requires_cargo_row_normalization(self):
        result = bridge("PARANAGUA", tables_paranagua(
            paranagua(), paranagua(volume="21.000,00", prog="PRG-6")
        ))
        self.assertEqual(result.source_rows, 2)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.excluded[0]["reason"], "duplicate_duv_requires_cargo_row_normalization")
        with self.assertRaisesRegex(ValueError, "partial lineup"):
            vintage_from_official_bridge(result, reference_date="2026-10-20", competence="2026-10")

    def test_date_only_itaqui_is_preserved_but_cannot_become_0000(self):
        raw = tables_itaqui(itaqui(eta="21/10/2026"))
        parsed = parse_itaqui_tables(raw, reference_date=date(2026, 10, 20))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["eta"], "")
        result = bridge("ITAQUI", raw)
        self.assertFalse(result.candidates)
        self.assertEqual(result.excluded[0]["reason"], "precise_pdf_eta_missing_or_invalid")

    def test_date_only_paranagua_is_preserved_but_excluded(self):
        raw = tables_paranagua(paranagua(eta="21/10/2026"))
        parsed = parse_paranagua_tables(raw, reference_date=date(2026, 10, 20),
                                        series="EXPORT_OESTE")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["eta"], "")
        result = bridge("PARANAGUA", raw)
        self.assertEqual(result.excluded[0]["reason"], "precise_pdf_eta_missing_or_invalid")

    def test_missing_paranagua_arrival_row_remains_visible_for_audit(self):
        raw = tables_paranagua(paranagua(eta=""))
        parsed = parse_paranagua_tables(raw, reference_date=date(2026, 10, 20),
                                        series="EXPORT_OESTE")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["eta"], "")
        result = bridge("PARANAGUA", raw)
        self.assertEqual(result.source_rows, 1)
        self.assertEqual(result.excluded[0]["reason"], "precise_pdf_eta_missing_or_invalid")

    def test_explicit_midnight_eta_is_different_from_date_only(self):
        result = bridge("ITAQUI", tables_itaqui(itaqui(eta="21/10/2026 00:00")))
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].eta, "2026-10-21T03:00:00+00:00")

    def test_inferred_year_with_clock_is_declared_unsafe(self):
        raw = tables_itaqui(itaqui(eta="21/10 09:00"))
        parsed = parse_itaqui_tables(raw, reference_date=date(2026, 10, 20))
        self.assertTrue(parsed[0]["eta_year_inferred"])
        result = bridge("ITAQUI", raw)
        self.assertFalse(result.candidates)
        self.assertEqual(result.excluded[0]["reason"], "pdf_eta_year_not_explicit")

    def test_two_digit_year_with_clock_is_not_four_digit_evidence(self):
        result = bridge("PARANAGUA", tables_paranagua(paranagua(eta="21/10/26 09:00")))
        self.assertEqual(result.excluded[0]["reason"], "pdf_eta_year_not_explicit")

    def test_distant_eta_is_excluded(self):
        result = bridge("ITAQUI", tables_itaqui(itaqui(eta="21/10/2029 09:00")))
        self.assertEqual(result.excluded[0]["reason"], "precise_pdf_eta_missing_or_invalid")

    def test_mixed_port_document_rejected_by_canonical_collector(self):
        bad = document("PARANAGUA")
        with mocked_tables(tables_itaqui(itaqui())):
            with self.assertRaises(ErroPorto):
                bridge_official_pdf_document(contract=contract("ITAQUI"), document=bad)

    def test_tampered_pdf_bytes_or_hash_rejected(self):
        bad = document()
        bad["sha256"] = "0" * 64
        with mocked_tables(tables_itaqui(itaqui())):
            with self.assertRaises(ErroPorto):
                bridge_official_pdf_document(contract=contract(), document=bad)

    def test_no_rights_collector_rejected(self):
        with mocked_tables(tables_itaqui(itaqui())):
            with self.assertRaises(PermissionError):
                bridge_official_pdf_document(contract=contract(granted=False), document=document())

    def test_later_acquisition_disallowed_for_asof(self):
        with mocked_tables(tables_itaqui(itaqui())):
            with self.assertRaises(ErroPorto):
                bridge_official_pdf_document(contract=contract(), document=document(),
                    captured_before="2026-10-19T08:00:00Z")

    def test_naive_asof_disallowed(self):
        with mocked_tables(tables_itaqui(itaqui())):
            with self.assertRaises(ErroPorto):
                bridge_official_pdf_document(contract=contract(), document=document(),
                    captured_before="2026-10-20T12:00:00")

    def test_parser_edition_mismatch_detected(self):
        with mocked_tables(tables_itaqui(itaqui()), bridge_tables=tables_itaqui(
             itaqui(vessel="DIFFERENT VESSEL"))):
            with self.assertRaisesRegex(ErroPorto, "disagrees"):
                bridge_official_pdf_document(contract=contract(), document=document())

    def test_html_contract_cannot_enter_pdf_bridge(self):
        fake = contract()
        wrong = ContratoPorto(porto=fake.porto, fonte=fake.fonte, modo="HTML_SANTOS_SCHEDULE")
        with self.assertRaisesRegex(ErroPorto, "requires registered"):
            bridge_official_pdf_document(contract=wrong, document=document())

    def test_incomplete_pdf_does_not_reinterpret_missing_duv_as_imo(self):
        result = bridge("ITAQUI", tables_itaqui(itaqui(duv="", vessel="VALID IMO ONLY")))
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.source_rows, 1)


if __name__ == "__main__":
    unittest.main()
