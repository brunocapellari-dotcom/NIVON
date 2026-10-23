"""Orquestrador de leitura pontual: nenhum acesso sem --live e stdout mínimo."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from nivon import hidromet_pontual_cli as cli


class TestHidrometCLI(unittest.TestCase):
    def test_todas_fontes_sao_silenciosas_sem_live(self):
        for fonte in ("inmet_estacoes","cptec_brasilapi","nasa_power","openmeteo","glofas","cemaden"):
            with self.subTest(fonte=fonte):
                with patch.object(cli,"consultar_glofas",side_effect=AssertionError("rede")):
                    r=cli.executar(["--fonte",fonte])
                self.assertEqual(r["estado"],"REDE_DESATIVADA")
                self.assertFalse(r["publicavel"])

    def test_live_glofas_apenas_summary(self):
        fixture={"registros":[{"data_referencia":"2026-10-21","river_discharge":50.0}],
                 "segredo":"NUNCA_IMPRIMIR"}
        with patch.object(cli,"consultar_glofas",return_value=fixture) as proc:
            r=cli.executar(["--fonte","glofas","--latitude","-12.5",
                           "--longitude","-55.7","--live"])
        proc.assert_called_once()
        self.assertEqual(r["quantidade_registros"],1)
        self.assertNotIn("NUNCA_IMPRIMIR",json.dumps(r))
        self.assertFalse(r["homologado"])

    def test_live_erro_sanitizado_nao_trava_cli(self):
        with patch.object(cli,"consultar_acumulados",side_effect=cli.ErroCemaden("segredo")):
            buf=io.StringIO()
            with redirect_stdout(buf):
                ret=cli.main(["--fonte","cemaden","--codigo-ibge","2927408","--live"])
        self.assertEqual(ret,2)
        self.assertNotIn("segredo",buf.getvalue())
        self.assertEqual(json.loads(buf.getvalue())["estado"],"CONSULTA_NAO_VALIDADA")


if __name__=="__main__":
    unittest.main()
