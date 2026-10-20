import unittest
from datetime import datetime
from nivon.motores import DadoInvalido
from nivon.pecuaria_mercados import (
    MERCADOS, selecionar_vintage_precos, tendencia_observada_pecuaria,
    backtest_sazonal_pecuaria,
)

SHA = "a" * 64
FONTE = "FONTE_SINTETICA"


def amostra(especie="BOVINO", indicador="BOI_GORDO", meses=40, delta=0):
    serie = []
    for i in range(meses):
        ano, indice = divmod(2023 * 12 + i, 12)
        mes = indice + 1
        competencia = f"{ano:04d}-{mes:02d}"
        valor = (100 + 2*i + 5*(mes % 3)) + delta
        serie.append({
            "especie": especie, "indicador": indicador,
            "unidade": MERCADOS[especie][indicador],
            "praca": "MT-SORRISO", "fonte_id": FONTE,
            "competencia": competencia, "data_referencia": competencia + "-20", "valor": float(valor),
            "publicacao": competencia + "-20T12:00:00Z",
            "coleta": competencia + "-21T12:00:00Z",
            "origem_sha256": SHA,
        })
    return serie


def args(especie="BOVINO", indicador="BOI_GORDO", **kw):
    return dict(serie=amostra(especie, indicador), especie=especie,
                indicador=indicador, praca="MT-SORRISO", fonte_id=FONTE,
                corte_asof="2026-04-01T00:00:00Z", **kw)


class TestPecuariaMercados(unittest.TestCase):
    def test_quatro_indicadores_sem_misturar_unidades(self):
        for especie, indicador in (("BOVINO", "BOI_GORDO"),
                                    ("BOVINO", "BEZERRO"),
                                    ("FRANGO", "FRANGO_VIVO"),
                                    ("SUINO", "SUINO_VIVO")):
            r = tendencia_observada_pecuaria(**args(especie, indicador))
            self.assertEqual(r["tendencia"], "ALTA")
            self.assertIsNone(r["probabilidade_alta"])
            self.assertFalse(r["previsao_homologada"])
            self.assertEqual(r["unidade"], MERCADOS[especie][indicador])

    def test_revisao_futura_nao_contamina_vintage_antigo(self):
        base = amostra(meses=24)
        antiga = base[-1].copy()
        antiga["valor"] = 999999.0
        antiga["publicacao"] = "2026-10-19T12:00:00Z"
        antiga["coleta"] = "2026-10-20T12:00:00Z"
        antiga["origem_sha256"] = "b"*64
        original = selecionar_vintage_precos(serie=base, especie="BOVINO",
            indicador="BOI_GORDO", praca="MT-SORRISO", fonte_id=FONTE,
            corte_asof="2025-01-01T00:00:00Z")
        alterado = selecionar_vintage_precos(serie=base+[antiga], especie="BOVINO",
            indicador="BOI_GORDO", praca="MT-SORRISO", fonte_id=FONTE,
            corte_asof="2025-01-01T00:00:00Z")
        self.assertEqual(original, alterado)

    def test_revisao_igual_instante_conflitante_bloqueada(self):
        serie = amostra(meses=2)
        conflitante = dict(serie[0], valor=10000)
        with self.assertRaises(DadoInvalido):
            selecionar_vintage_precos(serie=serie+[conflitante], especie="BOVINO",
                indicador="BOI_GORDO", praca="MT-SORRISO", fonte_id=FONTE,
                corte_asof="2026-10-20T00:00:00Z")

    def test_indeterminado_sem_quinze_meses_ou_lacuna(self):
        base = args()
        base["serie"] = amostra(meses=14)
        self.assertEqual(tendencia_observada_pecuaria(**base)["tendencia"], "INDETERMINADA")
        base["serie"] = amostra(meses=40)
        base["serie"].pop(26)
        self.assertEqual(tendencia_observada_pecuaria(**base)["tendencia"], "INDETERMINADA")

    def test_mistura_praca_cadeia_unidade_fonte_rejeitada(self):
        for alteracao in ({"praca": "SP"}, {"especie": "FRANGO"},
                          {"unidade": "BRL_KG_VIVO"}, {"fonte_id": "OUTRA"}):
            base = args()
            base["serie"][0].update(alteracao)
            with self.assertRaises(DadoInvalido):
                tendencia_observada_pecuaria(**base)

    def test_nao_inferir_probabilidade_sem_calibracao(self):
        resultado = backtest_sazonal_pecuaria(**args())
        self.assertGreaterEqual(resultado["folds_validos"], 12)
        self.assertTrue(resultado["avaliavel"])
        self.assertFalse(resultado["previsao_homologada"])
        self.assertFalse(resultado["probabilidades_calibradas"])
        self.assertGreaterEqual(resultado["mae_sazonal"], 0)

    def test_backtest_insuficiente_nao_avaliavel(self):
        a = args()
        a["serie"] = amostra(meses=15)
        r = backtest_sazonal_pecuaria(**a)
        self.assertFalse(r["avaliavel"])

    def test_rejeita_timestamp_sem_fuso_e_preco_anomalo(self):
        for mod in ({"publicacao": "2026-01-01T10:00:00"},
                    {"valor": -1}, {"valor": float("nan")},
                    {"origem_sha256": "abc"},
                    {"data_referencia": "2022-01-20"},
                    {"data_referencia": "2023-02-31"},
                    {"coleta": "2022-01-01T00:00:00Z"}):
            a = args()
            a["serie"][0].update(mod)
            with self.assertRaises(DadoInvalido):
                tendencia_observada_pecuaria(**a)

    def test_boi_nao_aceita_preco_vivo_de_frango(self):
        a = args()
        a["serie"][0]["indicador"] = "FRANGO_VIVO"
        with self.assertRaises(DadoInvalido):
            tendencia_observada_pecuaria(**a)


if __name__ == "__main__":
    unittest.main()
