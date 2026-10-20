import unittest
from datetime import date, datetime, timedelta, timezone

from nivon.qualidade_mercados import (
    ErroQualidadeMercado, preparar_serie_precos, tendencia_preco_auditada,
)

UTC = timezone.utc
SHA1 = "a" * 64
SHA2 = "b" * 64
SHA3 = "c" * 64


def row(d="2026-10-13", preco="1050.125", **kw):
    obj = {
        "mercado": "CME", "produto": "SOJA", "contrato": "2026-11",
        "tipo": "AJUSTE", "unidade": "USC/BU",
        "data_referencia": d, "competencia": d[:7],
        "referencia_em": d + "T16:00:00-04:00",
        "publicacao_em": d + "T16:30:00-04:00",
        "coleta_em": d + "T17:00:00-04:00",
        "fonte_id": "FONTE_TESTE", "fonte_url": "https://example.org/feed",
        "edicao_sha256": SHA1, "preco": preco,
    }
    obj.update(kw)
    return obj


def datas():
    return ["2026-10-07", "2026-10-08", "2026-10-09",
            "2026-10-13", "2026-10-14", "2026-10-15"]


class TestQualidadeMercado(unittest.TestCase):
    def test_serie_homogenea_e_tendencia_descritiva(self):
        a = [row(d, str(1050+i*5)) for i, d in enumerate(datas())]
        r = tendencia_preco_auditada(a, as_of="2026-10-20T12:00:00Z",
                                    janela=6, tolerancia_absoluta=5)
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertFalse(r["publicavel"])
        self.assertIsNone(r["probabilidades_calibradas"])

    def test_precisao_decimal_preservada(self):
        r = preparar_serie_precos([row(preco="1000.0125")],
                                  as_of="2026-10-20T12:00:00Z")
        self.assertEqual(r["serie"][0]["valor_decimal"], "1000.0125")

    def test_revisao_documentada(self):
        a = row(preco="1000")
        b = row(preco="1001", publicacao_em="2026-10-13T17:30:00-04:00",
                coleta_em="2026-10-13T18:00:00-04:00",
                edicao_sha256=SHA2, revisao_de_sha256=SHA1)
        resultado = preparar_serie_precos([b, a, dict(a)],
                                          as_of="2026-10-20T12:00:00Z")
        self.assertEqual(resultado["serie"][0]["valor_decimal"], "1001")
        self.assertEqual(resultado["revisoes_resolvidas"], 1)
        self.assertEqual(resultado["duplicatas_identicas"], 1)

    def test_duas_vintages_sem_cadeia_bloqueia(self):
        with self.assertRaisesRegex(ErroQualidadeMercado, "revisão"):
            preparar_serie_precos([row(preco="1000"), row(
                preco="1200", edicao_sha256=SHA2)],
                as_of="2026-10-20T12:00:00Z")

    def test_revisao_nao_pode_antecipar_publicacao(self):
        with self.assertRaises(ErroQualidadeMercado):
            preparar_serie_precos([
                row(preco="1000"),
                row(preco="1001", edicao_sha256=SHA2,
                    revisao_de_sha256=SHA1)],
                as_of="2026-10-20T12:00:00Z")

    def test_mesmo_sha_com_preco_diferente(self):
        with self.assertRaisesRegex(ErroQualidadeMercado, "mesmo SHA"):
            preparar_serie_precos([row(preco="1000"), row(preco="1001")],
                                  as_of="2026-10-20T12:00:00Z")

    def test_data_hora_do_futuro_bloqueia(self):
        with self.assertRaisesRegex(ErroQualidadeMercado, "point-in-time"):
            preparar_serie_precos([row(coleta_em="2026-10-20T13:00:00Z")],
                                  as_of="2026-10-20T12:00:00Z")

    def test_nao_aceita_timestamp_ingenuo(self):
        with self.assertRaisesRegex(ErroQualidadeMercado, "fuso"):
            preparar_serie_precos([row(referencia_em="2026-10-13T16:00:00")],
                                  as_of="2026-10-20T12:00:00Z")

    def test_vencimento_diferente_bloqueia(self):
        with self.assertRaisesRegex(ErroQualidadeMercado, "mistura"):
            preparar_serie_precos([row(), row(d="2026-10-14",
                                             contrato="2027-01")],
                                  as_of="2026-10-20T12:00:00Z")

    def test_fechar_nao_e_ajustar(self):
        with self.assertRaises(ErroQualidadeMercado):
            preparar_serie_precos([row(), row(d="2026-10-14",
                                             tipo="FECHAMENTO")],
                                  as_of="2026-10-20T12:00:00Z")

    def test_tipo_e_unidade_incoerentes(self):
        for alt in ({"unidade": "USD/T"}, {"tipo": "INDICADOR_FISICO"},
                    {"contrato": "2026-13"}, {"preco": True},
                    {"preco": "NaN"}, {"preco": "-1"}):
            with self.subTest(alt=alt), self.assertRaises(ErroQualidadeMercado):
                preparar_serie_precos([row(**alt)],
                                      as_of="2026-10-20T12:00:00Z")

    def test_fisico_nao_e_futuro(self):
        base = row(mercado="FISICO", contrato=None, localidade_ibge="5107602",
                   tipo="INDICADOR_FISICO", unidade="BRL/SC60KG", preco="140")
        r = preparar_serie_precos([base], as_of="2026-10-20T12:00:00Z")
        self.assertEqual(r["identidade_economica"][5], "5107602")
        with self.assertRaises(ErroQualidadeMercado):
            preparar_serie_precos([dict(base, localidade_ibge="4106902"), base],
                                  as_of="2026-10-20T12:00:00Z")

    def test_sem_licenca_implicita_ou_rede(self):
        r = preparar_serie_precos([row()], as_of="2026-10-20T12:00:00Z")
        self.assertFalse(r["publicavel"])
        self.assertNotIn("direitos_aprovados", r)
        with self.assertRaises(ErroQualidadeMercado):
            preparar_serie_precos([row(fonte_url="http://example.org/feed")],
                                  as_of="2026-10-20T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
