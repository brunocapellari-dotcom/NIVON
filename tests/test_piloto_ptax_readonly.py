"""Contrato E2E do piloto BCB read-only: fonte → parser → frescor → relatório."""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch

from nivon.piloto_ptax_readonly import ErroPiloto, executar, main, obter_json_oficial

NOW=datetime(2026,10,25,18,0,tzinfo=timezone.utc)
GOOD={
    "value":[
        {"cotacaoCompra":5.21,"cotacaoVenda":5.23,"dataHoraCotacao":"2026-10-22 13:10:00.0000"},
        {"cotacaoCompra":5.31,"cotacaoVenda":5.33,"dataHoraCotacao":"2026-10-23 13:10:00.0000"},
    ]
}


class PilotoPTAXE2E(unittest.TestCase):
    def simulated(self, fixture=GOOD, now=NOW):
        def get(url):
            self.assertTrue(url.startswith("https://olinda.bcb.gov.br/olinda/servico/PTAX/"))
            self.assertIn("CotacaoDolarPeriodo(",url)
            self.assertIn("%2710-16-2026%27",url)
            self.assertIn("%2710-25-2026%27",url)
            return json.dumps(fixture).encode()
        return executar(agora=now,buscar=get)

    def test_live_contract_pipeline_with_weekend_and_previous_valid_day(self):
        d=self.simulated()
        self.assertEqual(d["status"],"PREVIA_INTERNA_VALIDA")
        self.assertEqual(d["cotacao_compra"],5.31)
        self.assertEqual(d["cotacao_venda"],5.33)
        self.assertAlmostEqual(d["variacao_venda_pct_vs_dia_anterior_observado"],
                               round((5.33/5.23-1)*100,4))
        self.assertEqual(d["competencia"],"2026-10-23")
        self.assertEqual(d["observacoes_no_recorte"],2)
        self.assertIs(d["consulta_ao_vivo_executada"],False)
        for flag in ("rotina_agendada_ativa","publicacao_autorizada",
                     "whatsapp_enviado","aprovado_go_live"):
            self.assertIs(d[flag],False)

    def test_no_previous_day_never_invents_price_change(self):
        fixture={"value":[GOOD["value"][-1]]}
        d=self.simulated(fixture)
        self.assertIsNone(d["variacao_venda_pct_vs_dia_anterior_observado"])
        self.assertIs(d["ultimo_valor_anterior_disponivel"],False)

    def test_stale_data_never_exposes_past_price_as_current(self):
        now=datetime(2026,10,29,18,0,tzinfo=timezone.utc)
        def get(_):
            return json.dumps({"value":[GOOD["value"][-1]]}).encode()
        d=executar(agora=now,buscar=get)
        self.assertEqual(d["status"],"INDISPONIVEL_FRESCURA")
        self.assertIsNone(d["cotacao_venda"])
        self.assertIs(d["aprovado_go_live"],False)

    def test_untrusted_json_future_duplicate_pagination_and_zero_are_blocked(self):
        cases=[
            json.dumps({"value":[]}).encode(),
            json.dumps({"value":[GOOD["value"][0],GOOD["value"][0]]}).encode(),
            b'{"value":[],"value":[]}',
            json.dumps({"value":[{"cotacaoCompra":0,"cotacaoVenda":5,
                                  "dataHoraCotacao":"2026-10-23 13:10"}]}).encode(),
            json.dumps({"value":[{"cotacaoCompra":5,"cotacaoVenda":5.1,
                                  "dataHoraCotacao":"2026-10-26 13:10"}]}).encode(),
            json.dumps({**GOOD,"@odata.nextLink":"https://external.invalid"}).encode(),
        ]
        for data in cases:
            with self.subTest(data=data[:50]),self.assertRaises(ErroPiloto):
                executar(agora=NOW,buscar=lambda _:data)

    def test_full_flow_rejects_unsafe_url_before_network(self):
        for url in ("https://evil.invalid/api","http://olinda.bcb.gov.br/path",
                    "https://olinda.bcb.gov.br@evil.invalid/",
                    "https://olinda.bcb.gov.br/other"):
            with self.subTest(url=url),self.assertRaisesRegex(ErroPiloto,"endpoint"):
                obter_json_oficial(url)

    def test_bad_clock_or_scope_fail_without_contacting_bcb(self):
        with patch("nivon.piloto_ptax_readonly.obter_json_oficial") as client:
            with self.assertRaisesRegex(ErroPiloto,"fuso"):
                executar(agora=datetime(2026,10,25))
            client.assert_not_called()
        for days in (0,2,11,True):
            with self.subTest(days=days),self.assertRaisesRegex(ErroPiloto,"janela"):
                executar(agora=NOW,dias=days)

    def test_cli_requires_explicit_live_flag_and_never_contacts_source_implicitly(self):
        with patch("sys.argv",["prog"]),patch(
                "nivon.piloto_ptax_readonly.obter_json_oficial") as client:
            with self.assertRaises(SystemExit) as context:
                main()
            self.assertEqual(context.exception.code,2)
            client.assert_not_called()

    def test_cli_masks_prices_in_public_logs(self):
        with patch("sys.argv",["prog","--consultar-bcb"]),patch(
                "nivon.piloto_ptax_readonly.executar",return_value=self.simulated()):
            out=io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(),0)
            printed=json.loads(out.getvalue())
            self.assertNotIn("cotacao_venda",printed)
            self.assertNotIn("cotacao_compra",printed)
            self.assertNotIn("variacao_venda_pct_vs_dia_anterior_observado",printed)
            self.assertEqual(printed["status"],"PREVIA_INTERNA_VALIDA")


if __name__=="__main__":
    unittest.main()
