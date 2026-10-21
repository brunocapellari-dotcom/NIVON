"""NIVON source guard regression tests — fixtures only, no external data."""
from datetime import date, datetime, timezone
import unittest

from nivon.fontes_agrobr import (
    DadosNaoHomologados, consultar_cepea_para_validacao, decimal_preco,
    estado_fontes, inspecionar_imea, permissao_consulta, validar_cepea,
)


def cepea(**kw):
    r = {
        "data": "2026-10-20", "produto": "soja", "praca": "Paranaguá/PR",
        "valor": 127.5, "unidade": "BRL/sc60kg", "fonte": "cepea",
        "anomalies": None,
    }
    return dict(r, **kw)


def imea(**kw):
    r = {"cadeia": "soja", "indicador_id": "708192508838936580",
         "indicador": "Preço soja disponível compra", "localidade": "Sorriso",
         "valor": 112.5, "unidade": "R$/sc", "safra": "25/26",
         "data_publicacao": "2026-10-20T12:00:00"}
    return dict(r, **kw)


class TestFontesAgrobr(unittest.TestCase):
    def test_cepea_precisa_aceite_explicito(self):
        with self.assertRaises(DadosNaoHomologados):
            permissao_consulta("cepea")
        permissao_consulta("cepea", aceite_nc=True)

    def test_imea_restrita_por_padrao(self):
        with self.assertRaises(DadosNaoHomologados):
            permissao_consulta("imea")
        with self.assertRaises(DadosNaoHomologados):
            permissao_consulta("imea", autorizacao_imea="ok")
        permissao_consulta("imea", autorizacao_imea="autorizacao-2026")

    def test_cepea_valida_proveniencia_e_datas(self):
        d = validar_cepea([cepea()], aceite_nc=True,
                           fontes_meta=["cepea"],
                           data_coleta=datetime(2026, 10, 21, tzinfo=timezone.utc))
        self.assertEqual(d["contagem"], 1)
        self.assertEqual(d["rejeitados"], 0)
        row = d["candidatos"][0]
        self.assertEqual(row["valor"], "127.5")
        self.assertEqual(row["data_referencia"], "2026-10-20")
        self.assertEqual(row["competencia"], "2026-10")
        self.assertIsNone(row["data_publicacao"])
        self.assertEqual(row["classificacao"], "INFORMADO")

    def test_fallback_imea_e_noticias_rejeitados(self):
        with self.assertRaises(DadosNaoHomologados):
            validar_cepea([cepea()], aceite_nc=True,
                           fontes_meta=["cepea", "noticias_agricolas"])
        out = validar_cepea([cepea(fonte="noticias_agricolas")], aceite_nc=True)
        self.assertEqual(out["contagem"], 0)
        self.assertEqual(out["quarentena"], ["FONTE_NAO_CEPEA"])

    def test_cepea_anomalias_preco_zero_e_futuro_quarentena(self):
        registros = [cepea(anomalies='["out_of_range: valor"]'),
                     cepea(valor=0), cepea(valor=float("nan")),
                     cepea(data="2026-10-22"), cepea(unidade="")]
        res = validar_cepea(registros, aceite_nc=True,
                            data_coleta=datetime(2026, 10, 21, tzinfo=timezone.utc))
        self.assertEqual(res["contagem"], 0)
        self.assertEqual(res["rejeitados"], 5)

    def test_nao_confunde_publicacao_com_referencia_imea(self):
        out = inspecionar_imea([imea()], autorizacao_imea="documento-validado")
        self.assertEqual(out["contagem"], 1)
        self.assertEqual(out["publicaveis_tendencia"], 0)
        self.assertIsNone(out["candidatos_quarentenados"][0]["data_referencia"])
        self.assertEqual(out["candidatos_quarentenados"][0]["estado"],
                         "AGUARDA_DATA_REFERENCIA")

    def test_imea_semente_zero_duplicado(self):
        out = inspecionar_imea([imea(), imea(), imea(valor=0),
                                imea(indicador="SEMENTE SOJA BRANCA (R$/sc 40kg)")],
                                autorizacao_imea="documento-validado")
        self.assertEqual(out["contagem"], 1)
        self.assertEqual(out["quarentena"].count("DUPLICATA_EXATA"), 1)
        self.assertIn("PRECO_NAO_POSITIVO_OU_AUSENTE", out["quarentena"])
        self.assertIn("SEMENTE_NAO_PRECO_GRAO", out["quarentena"])

    def test_rejeita_decimal_ambigua(self):
        for v in (0, -2, None, "nan", float("inf"), "não cotado", True):
            with self.subTest(v=v), self.assertRaises(ValueError):
                decimal_preco(v)

    def test_estado_nenhuma_gravacao_real(self):
        e = estado_fontes()
        self.assertFalse(e["cepea"]["gravacao_automatica"])
        self.assertFalse(e["imea"]["gravacao_automatica"])


if __name__ == "__main__":
    unittest.main()
