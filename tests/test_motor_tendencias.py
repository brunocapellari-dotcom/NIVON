import unittest
from datetime import date, timedelta

from nivon.motor_tendencias import ErroTendencia, tendencia_observada, tendencia_projetada


SHA = "a" * 64


def diario(valores, inicio=date(2026, 10, 1)):
    return [
        {"periodo": (inicio+timedelta(days=i)).isoformat(),
         "publicacao": (inicio+timedelta(days=i)).isoformat(),
         "coleta": (inicio+timedelta(days=i)).isoformat(),
         "valor": v, "fonte_id": "TESTE", "edicao_sha256": SHA}
        for i, v in enumerate(valores)
    ]


def mensal(valores, ano=2024, mes=1):
    linhas = []
    for i, v in enumerate(valores):
        k = ano*12 + (mes-1) + i
        periodo = f"{k//12:04d}-{k%12+1:02d}-01"
        linhas.append({"periodo": periodo, "publicacao": periodo, "coleta": periodo,
                       "valor": v, "fonte_id": "TESTE", "edicao_sha256": SHA})
    return linhas


def observada(serie, **kwargs):
    return tendencia_observada(
        serie, as_of="2026-10-20", fonte_id="TESTE", unidade="R$/t",
        frequencia="DIARIA", janela=6,
        tolerancia_absoluta=1, tolerancia_relativa=0, **kwargs
    )


def cenarios(base, itens, alvo="2026-11-20"):
    return [
        {"modelo_id": f"M{i}", "valor": valor, "peso": peso,
         "emitido_em": "2026-10-20", "alvo_periodo": alvo}
        for i, (valor, peso) in enumerate(itens)
    ]


class TestMotorTendencias(unittest.TestCase):

    def test_alta_gradual(self):
        r = observada(diario([100, 103, 106, 109, 112, 115]))
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertEqual(r["intensidade"], "FORTE")
        self.assertEqual(r["orientacao"], "OBSERVADA")
        self.assertIsNone(r["probabilidades_calibradas"])
        self.assertFalse(r["publicavel"])

    def test_baixa_gradual(self):
        r = observada(diario([115, 112, 109, 106, 103, 100]))
        self.assertEqual(r["tendencia"], "BAIXA")

    def test_estabilidade_mesmo_valor(self):
        r = observada(diario([100]*6))
        self.assertEqual(r["tendencia"], "ESTABILIDADE")
        self.assertIsNone(r["intensidade"])

    def test_estabilidade_pouco_ruido(self):
        r = observada(diario([100, 100.4, 99.8, 100.2, 99.7, 100]))
        self.assertEqual(r["tendencia"], "ESTABILIDADE")

    def test_oscilacao_nao_e_estabilidade(self):
        r = observada(diario([100, 110, 90, 111, 89, 101]))
        self.assertEqual(r["tendencia"], "INDETERMINADA")

    def test_falta_de_historico_nao_gera_tendencia(self):
        r = observada(diario([1, 2, 3]))
        self.assertEqual(r["status"], "DADOS_INSUFICIENTES")
        self.assertEqual(r["tendencia"], "INDETERMINADA")

    def test_sazonal_mensal_com_crescimento_interanual(self):
        v = [90, 95, 100, 105, 110, 115, 120, 125, 130, 135, 140, 145]
        r = tendencia_observada(mensal(v + [x+20 for x in v]),
                as_of="2026-10-20", fonte_id="TESTE", unidade="toneladas",
                frequencia="MENSAL", janela=6, sazonalidade=12,
                tolerancia_absoluta=5, tolerancia_relativa=0)
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertEqual(r["metodo"], "MEDIANA_VARIACOES_INTERANUAIS")
        self.assertAlmostEqual(r["deslocamento_descritivo"], 20)

    def test_nao_aceita_lacuna_diaria(self):
        serie = diario([1, 2, 3, 4, 5, 6])
        serie[2]["periodo"] = "2026-10-05"
        with self.assertRaises(ErroTendencia):
            observada(serie)

    def test_nao_aceita_duplicidade_e_vintages(self):
        serie = diario([1, 2, 3, 4, 5, 6])
        serie[2]["periodo"] = serie[1]["periodo"]
        with self.assertRaisesRegex(ErroTendencia, "duplicado"):
            observada(serie)

    def test_nao_aceita_data_posterior_ao_corte(self):
        serie = diario([1, 2, 3, 4, 5, 6])
        serie[0]["coleta"] = "2026-10-21"
        with self.assertRaises(ErroTendencia):
            observada(serie)

    def test_nao_aceita_publicacao_depois_de_coleta(self):
        serie = diario([1, 2, 3, 4, 5, 6])
        serie[0]["publicacao"] = "2026-10-02"
        with self.assertRaises(ErroTendencia):
            observada(serie)

    def test_nao_aceita_sem_sha_da_edicao(self):
        serie = diario([1, 2, 3, 4, 5, 6])
        del serie[3]["edicao_sha256"]
        with self.assertRaises(ErroTendencia):
            observada(serie)

    def test_nan_bool_inf_bloqueados(self):
        for invalido in [float("nan"), float("inf"), True]:
            with self.subTest(invalido=str(invalido)):
                serie = diario([1, 2, 3, 4, 5, invalido])
                with self.assertRaises(ErroTendencia):
                    observada(serie)

    def test_negativo_so_com_autorizacao_explicita(self):
        serie = diario([-5, -4, -3, -2, -1, 0])
        with self.assertRaises(ErroTendencia):
            observada(serie)
        r = tendencia_observada(
            serie, as_of="2026-10-20", fonte_id="TESTE", unidade="graus C",
            frequencia="DIARIA", janela=6, tolerancia_absoluta=1,
            tolerancia_relativa=0, nao_negativo=False)
        self.assertEqual(r["tendencia"], "ALTA")

    def test_limiar_percentual_por_indicador(self):
        serie = diario([100, 101, 102, 103, 104, 105])
        r = tendencia_observada(
            serie, as_of="2026-10-20", fonte_id="TESTE", unidade="R$/t",
            frequencia="DIARIA", janela=6, tolerancia_relativa=.1)
        self.assertEqual(r["tendencia"], "ESTABILIDADE")

    def test_projetada_consenso_nao_equivale_probabilidade(self):
        base = diario([100])[-1]
        r = tendencia_projetada(base, cenarios(base, [(110, .4), (115, .3), (105, .3)]),
            as_of="2026-10-20", fonte_id="TESTE", unidade="R$/t",
            tolerancia_absoluta=2, tolerancia_relativa=0)
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertEqual(r["participacao_ponderada_cenarios"]["ALTA"], 1.0)
        self.assertIsNone(r["probabilidades_calibradas"])
        self.assertFalse(r["publicavel"])

    def test_projetada_divergencia_indeterminada(self):
        base = diario([100])[-1]
        r = tendencia_projetada(base, cenarios(base, [(110, .4), (90, .3), (100, .3)]),
            as_of="2026-10-20", fonte_id="TESTE", unidade="R$/t",
            tolerancia_absoluta=2, tolerancia_relativa=0)
        self.assertEqual(r["tendencia"], "INDETERMINADA")

    def test_projetada_ponderacao_nao_soma_1(self):
        base = diario([100])[-1]
        with self.assertRaisesRegex(ErroTendencia, "somar 1"):
            tendencia_projetada(base, cenarios(base, [(110, .5), (111, .3), (112, .3)]),
                as_of="2026-10-20", fonte_id="TESTE", unidade="R$/t",
                tolerancia_absoluta=2, tolerancia_relativa=0)

    def test_projetada_espera_mesmo_horizonte(self):
        base = diario([100])[-1]
        c = cenarios(base, [(110, .4), (105, .3), (100, .3)])
        c[2]["alvo_periodo"] = "2027-03-20"
        with self.assertRaisesRegex(ErroTendencia, "horizontes diferentes"):
            tendencia_projetada(base, c, as_of="2026-10-20",
                fonte_id="TESTE", unidade="R$/t", tolerancia_absoluta=2)

    def test_projetada_proibe_previsao_do_passado(self):
        base = diario([100])[-1]
        c = cenarios(base, [(110, .4), (105, .3), (100, .3)], alvo="2026-10-19")
        with self.assertRaises(ErroTendencia):
            tendencia_projetada(base, c, as_of="2026-10-20",
                fonte_id="TESTE", unidade="R$/t", tolerancia_absoluta=2)

    def test_nao_executa_rede_ou_instala_dependencia_extra(self):
        import nivon.motor_tendencias as engine
        self.assertFalse(hasattr(engine, "requests"))
        self.assertFalse(hasattr(engine, "httpx"))


    def test_pregoes_com_fim_de_semana_nao_sao_serie_diaria(self):
        serie = diario([100, 101, 102, 103, 104, 105])
        dias = ["2026-10-09", "2026-10-13", "2026-10-14",
                "2026-10-15", "2026-10-16", "2026-10-19"]
        for row, dt in zip(serie, dias):
            row["periodo"] = row["publicacao"] = row["coleta"] = dt
        r = tendencia_observada(
            serie, as_of="2026-10-20", fonte_id="TESTE", unidade="centavos/bu",
            frequencia="SESSOES", janela=6, tolerancia_absoluta=1)
        self.assertEqual(r["tendencia"], "ALTA")
        with self.assertRaises(ErroTendencia):
            observada(serie)

    def test_sem_limiar_expresso_bloqueia(self):
        with self.assertRaisesRegex(ErroTendencia, "limiar"):
            tendencia_observada(
                diario([1, 2, 3, 4, 5, 6]), as_of="2026-10-20",
                fonte_id="TESTE", unidade="R$/t", frequencia="DIARIA")


if __name__ == "__main__":
    unittest.main()
