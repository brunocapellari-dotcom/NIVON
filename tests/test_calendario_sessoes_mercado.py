import unittest
from nivon.calendario_sessoes_mercado import (
    ErroCalendarioMercado, validar_cobertura_calendario,
)

PERIODOS = ("2026-10-07", "2026-10-08", "2026-10-09",
            "2026-10-13", "2026-10-14", "2026-10-15")
CORTE = "2026-10-20T12:00:00Z"


def cal(**alteracoes):
    x = {
        "mercado": "CME",
        "fonte_id": "CAL-TESTE",
        "edicao_sha256": "a" * 64,
        "publicacao_em": "2026-10-01T09:00:00-04:00",
        "coleta_em": "2026-10-01T10:00:00-04:00",
        "sessoes": list(PERIODOS),
    }
    x.update(alteracoes)
    return x


class TestCalendarioMercados(unittest.TestCase):
    def test_cobertura_corretamente_declarada(self):
        r = validar_cobertura_calendario(cal(), mercado="CME",
                                         periodos=PERIODOS, as_of=CORTE)
        self.assertEqual(r["sessoes_conferidas"], 6)
        self.assertEqual(r["status"], "COBERTURA_DECLARADA_NAO_HOMOLOGADA")
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["calendario_oficial_comprovado"])

    def test_recorte_de_janela_dentro_de_calendario_longo(self):
        r = validar_cobertura_calendario(
            cal(), mercado="CME", periodos=PERIODOS[-4:], as_of=CORTE)
        self.assertEqual(r["sessoes_conferidas"], 4)

    def test_mercado_incorreto(self):
        with self.assertRaisesRegex(ErroCalendarioMercado, "diferente"):
            validar_cobertura_calendario(cal(mercado="ICE"),
                                         mercado="CME", periodos=PERIODOS,
                                         as_of=CORTE)

    def test_sem_cobertura_de_periodos(self):
        with self.assertRaisesRegex(ErroCalendarioMercado, "não cobre"):
            validar_cobertura_calendario(cal(sessoes=list(PERIODOS[:-1])),
                                         mercado="CME", periodos=PERIODOS,
                                         as_of=CORTE)

    def test_sessao_faltante_no_preco(self):
        c = cal(sessoes=list(PERIODOS[:3]) + ["2026-10-12"] +
                          list(PERIODOS[3:]))
        with self.assertRaisesRegex(ErroCalendarioMercado, "lacuna"):
            validar_cobertura_calendario(c, mercado="CME",
                                         periodos=PERIODOS, as_of=CORTE)

    def test_calendario_nao_pode_ter_duplicatas(self):
        for sessoes in (list(PERIODOS) + [PERIODOS[-1]],
                        list(reversed(PERIODOS))):
            with self.subTest(sessoes=sessoes):
                with self.assertRaisesRegex(ErroCalendarioMercado, "ordem"):
                    validar_cobertura_calendario(
                        cal(sessoes=sessoes), mercado="CME",
                        periodos=PERIODOS, as_of=CORTE)

    def test_edicao_coletada_apos_corte(self):
        with self.assertRaisesRegex(ErroCalendarioMercado, "depois do corte"):
            validar_cobertura_calendario(
                cal(coleta_em="2026-10-20T13:00:00Z"),
                mercado="CME", periodos=PERIODOS, as_of=CORTE)

    def test_data_e_fuso_invalidos(self):
        for sobrescrita in (
            {"publicacao_em": "2026-10-01T09:00:00"},
            {"sessoes": ["2026-10-99"]},
            {"edicao_sha256": "INVALIDO"},
        ):
            with self.subTest(x=sobrescrita), self.assertRaises(ErroCalendarioMercado):
                validar_cobertura_calendario(
                    cal(**sobrescrita), mercado="CME",
                    periodos=PERIODOS, as_of=CORTE)


if __name__ == "__main__":
    unittest.main()
