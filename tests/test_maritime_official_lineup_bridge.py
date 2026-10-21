"""Fixture offline da autoridade: nunca criar ETA, DUV ou movimento realizado."""
import hashlib
import unittest
from datetime import datetime, timezone

from nivon.coleta_web import FonteWeb
from nivon.portos_automaticos import ContratoPorto, ErroPorto
from nivon.maritime.official_lineup_bridge import bridge_official_html_document

URL = "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracacoes-programadas/"
STAMP = "2026-10-20T12:00:00Z"


def contract():
    return ContratoPorto(
        porto="SANTOS", modo="HTML_SANTOS_SCHEDULE",
        fonte=FonteWeb(
            fonte_id="APS_PROGRAMACAO_FIXTURE",
            url=URL, dominio_autorizado="www.portodesantos.com.br",
            formato="HTML", status_direitos="APROVADA",
            operacoes_permitidas=frozenset({"COLETA"}),
        ),
    )


def row(vessel="NAVIO A", duv="12345", eta="21/10/2026 09:30", cargo="SOJA"):
    return f"<tr><td>{vessel}</td><td>9074729</td><td>{eta}</td><td>{duv}</td><td>T1</td><td>{cargo}</td></tr>"


def document(*rows, timestamp=STAMP):
    cells = "".join(rows)
    html = f"""<html><body><table>
        <thead><tr><th>Navio</th><th>IMO</th><th>ETA</th><th>DUV</th><th>Local</th><th>Carga</th></tr></thead>
        <tbody>{cells}</tbody></table></body></html>""".encode()
    return {
        "conteudo": html, "sha256": hashlib.sha256(html).hexdigest(),
        "url": URL, "fonte_id": "APS_PROGRAMACAO_FIXTURE",
        "mime": "text/html", "bytes": len(html), "capturado_em": timestamp,
    }


class TestOfficialBridge(unittest.TestCase):
    def test_valid_aps_schedule_has_local_zone_and_is_not_realized(self):
        result = bridge_official_html_document(
            contract=contract(), document=document(row()))
        self.assertEqual(result.port_id, "SANTOS")
        self.assertEqual(result.source_rows, 1)
        self.assertEqual(len(result.candidates), 1)
        call = result.candidates[0]
        self.assertEqual(call.eta, "2026-10-21T12:30:00+00:00")
        self.assertTrue(call.call_id.endswith(":12345"))
        self.assertEqual(call.lineup_status, "PROGRAMMED")
        self.assertFalse(result.publication_allowed)
        self.assertFalse(result.realized_cargo_claimed)
        self.assertEqual(result.summary()["usable_eta_calls"], 1)

    def test_date_only_is_excluded_instead_of_midnight(self):
        result = bridge_official_html_document(
            contract=contract(), document=document(row(eta="21/10/2026")))
        self.assertEqual(len(result.candidates), 0)
        self.assertEqual(result.excluded[0]["reason"], "eta_date_only")

    def test_missing_duv_excluded(self):
        result = bridge_official_html_document(
            contract=contract(), document=document(row(duv="")))
        self.assertFalse(result.candidates)
        self.assertEqual(result.excluded[0]["reason"], "official_call_id_missing")

    def test_duplicate_duv_does_not_double_count(self):
        result = bridge_official_html_document(
            contract=contract(), document=document(row(), row(vessel="NAVIO B")))
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.excluded[0]["reason"], "duplicate_call_id")

    def test_source_tamper_blocked(self):
        data = document(row())
        data["sha256"] = "0"*64
        with self.assertRaises(ErroPorto):
            bridge_official_html_document(contract=contract(), document=data)

    def test_bad_source_url_blocked(self):
        data = document(row())
        data["url"] = "https://evil.example/fake"
        with self.assertRaises(ErroPorto):
            bridge_official_html_document(contract=contract(), document=data)

    def test_future_collection_after_asof_blocked(self):
        with self.assertRaises(ErroPorto):
            bridge_official_html_document(
                contract=contract(), document=document(row()),
                captured_before="2026-10-19T12:00:00Z",
            )

    def test_unsupported_eta_excluded(self):
        result = bridge_official_html_document(
            contract=contract(), document=document(row(eta="amanha")))
        self.assertEqual(result.excluded[0]["reason"], "eta_format_unsupported")

    def test_past_or_far_future_eta_excluded(self):
        for eta in ("01/01/2020 08:00", "01/01/2029 08:00"):
            result = bridge_official_html_document(
                contract=contract(), document=document(row(eta=eta)))
            self.assertEqual(result.excluded[0]["reason"], "eta_outside_authority_window")

    def test_does_not_fetch_from_network(self):
        result = bridge_official_html_document(
            contract=contract(), document=document(row()))
        self.assertTrue(result.candidates)


if __name__ == "__main__":
    unittest.main()
