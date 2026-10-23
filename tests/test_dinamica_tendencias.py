"""Fixtures sintéticas e ataques de fronteira temporal para a força da tendência."""
import unittest
from datetime import date, timedelta

from nivon.dinamica_tendencias import comparar_forca_tendencia
from nivon.motor_tendencias import ErroTendencia

SHA = "c" * 64


def diario(valores):
    d = date(2026, 10, 1)
    return [
        {"periodo": (d + timedelta(days=i)).isoformat(),
         "publicacao": (d + timedelta(days=i)).isoformat(),
         "coleta": (d + timedelta(days=i)).isoformat(),
         "valor": v, "fonte_id": "TESTE-FRETE",
         "edicao_sha256": SHA}
        for i, v in enumerate(valores)
    ]


def comparar(valores, **extra):
    params = {
        "as_of": "2026-10-20", "fonte_id": "TESTE-FRETE",
        "unidade": "BRL/T", "frequencia": "DIARIA",
        "janela": 6, "tolerancia_absoluta": 1,
        "mudanca_minima_forca_em_limiares": 1,
    }
    params.update(extra)
    return comparar_forca_tendencia(
        valores if isinstance(valores, (list, tuple)) and valores and isinstance(valores[0], dict)
        else diario(valores),
        **params,
    )


class TestDinamicaTendencias(unittest.TestCase):
    def test_alta_ganha_forca(self):
        r = comparar([100, 101, 102, 103, 104, 105,
                     106, 109, 112, 115, 118, 121])
        self.assertEqual(r["tendencia_anterior"], "ALTA")
        self.assertEqual(r["tendencia_atual"], "ALTA")
        self.assertEqual(r["dinamica"], "AUMENTO_DE_FORCA")
        self.assertEqual(r["forca_anterior_em_limiares"], 5)
        self.assertEqual(r["forca_atual_em_limiares"], 15)
        self.assertEqual(r["janela_anterior"], ["2026-10-01", "2026-10-06"])
        self.assertEqual(r["janela_atual"], ["2026-10-07", "2026-10-12"])
        self.assertIsNone(r["probabilidades_calibradas"])
        self.assertFalse(r["publicavel"])

    def test_alta_perde_forca(self):
        r = comparar([100, 104, 108, 112, 116, 120,
                     122, 123, 124, 125, 126, 127])
        self.assertEqual(r["dinamica"], "PERDA_DE_FORCA")
        self.assertEqual(r["tendencia_atual"], "ALTA")

    def test_baixa_ganha_forca(self):
        r = comparar([170, 168, 166, 164, 162, 160,
                     158, 154, 150, 146, 142, 138])
        self.assertEqual(r["dinamica"], "AUMENTO_DE_FORCA")
        self.assertEqual(r["tendencia_atual"], "BAIXA")

    def test_reversao_alta_para_baixa(self):
        r = comparar([100, 102, 104, 106, 108, 110,
                     110, 108, 106, 104, 102, 100])
        self.assertEqual(r["dinamica"], "REVERSAO_OBSERVADA")
        self.assertEqual(r["tendencia_anterior"], "ALTA")
        self.assertEqual(r["tendencia_atual"], "BAIXA")

    def test_reversao_baixa_para_alta(self):
        r = comparar([110, 108, 106, 104, 102, 100,
                     100, 102, 104, 106, 108, 110])
        self.assertEqual(r["dinamica"], "REVERSAO_OBSERVADA")

    def test_persistencia_estavel(self):
        r = comparar([100] * 12)
        self.assertEqual(r["dinamica"], "ESTABILIDADE_PERSISTENTE")
        self.assertEqual(r["tendencia_atual"], "ESTABILIDADE")

    def test_saida_estabilidade(self):
        r = comparar([100] * 6 + [100, 102, 104, 106, 108, 110])
        self.assertEqual(r["dinamica"], "SAIDA_DA_ESTABILIDADE")

    def test_entrada_estabilidade(self):
        r = comparar([100, 102, 104, 106, 108, 110] + [110] * 6)
        self.assertEqual(r["dinamica"], "ENTRADA_EM_ESTABILIDADE")

    def test_forca_sem_mudanca_relevante(self):
        r = comparar([100, 102, 104, 106, 108, 110,
                      112, 114, 116, 118, 120, 122])
        self.assertEqual(r["dinamica"], "FORCA_SEM_ALTERACAO_RELEVANTE")

    def test_ruido_no_passado_nao_vira_reversao(self):
        r = comparar([100, 110, 90, 111, 89, 101,
                      102, 104, 106, 108, 110, 112])
        self.assertEqual(r["dinamica"], "INDETERMINADA")
        self.assertEqual(r["tendencia_anterior"], "INDETERMINADA")

    def test_ruido_atual_nao_vira_falsa_perda_de_forca(self):
        r = comparar([100, 102, 104, 106, 108, 110,
                      110, 125, 105, 124, 106, 111])
        self.assertEqual(r["dinamica"], "INDETERMINADA")

    def test_dados_insuficientes(self):
        r = comparar([100] * 11)
        self.assertEqual(r["status"], "DADOS_INSUFICIENTES")
        self.assertEqual(r["necessarias"], 12)
        self.assertIsNone(r["probabilidades_calibradas"])

    def test_lacuna_exatamente_entre_janelas_bloqueia(self):
        serie = diario([100, 101, 102, 103, 104, 105,
                        106, 107, 108, 109, 110, 111])
        for i in range(6, 12):
            dt = date(2026, 10, 1) + timedelta(days=i+1)
            serie[i]["periodo"] = serie[i]["publicacao"] = serie[i]["coleta"] = dt.isoformat()
        with self.assertRaisesRegex(ErroTendencia, "frequência"):
            comparar(serie)

    def test_versao_revisada_future_em_primeira_janela_bloqueia(self):
        serie = diario([100] * 12)
        serie[2]["coleta"] = "2026-10-21"
        with self.assertRaisesRegex(ErroTendencia, "vazamento temporal"):
            comparar(serie)

    def test_mistura_fontes_nao_passa(self):
        serie = diario([100] * 12)
        serie[3]["fonte_id"] = "OUTRA_FONTE"
        with self.assertRaisesRegex(ErroTendencia, "mistura de fontes"):
            comparar(serie)

    def test_negativos_exigem_autorizacao_explicita(self):
        serie = diario([5, 4, 3, 2, 1, -1,
                        -2, -3, -4, -5, -6, -7])
        with self.assertRaisesRegex(ErroTendencia, "negativo proibido"):
            comparar(serie)
        r = comparar(serie, nao_negativo=False)
        self.assertEqual(r["dinamica"], "FORCA_SEM_ALTERACAO_RELEVANTE")

    def test_usa_bandas_relativas_para_comparar_movimento_adimensional(self):
        r = comparar([100, 101, 102, 103, 104, 105,
                      106, 108, 110, 112, 114, 116],
                     tolerancia_absoluta=0, tolerancia_relativa=.01)
        self.assertEqual(r["dinamica"], "AUMENTO_DE_FORCA")
        self.assertGreater(r["forca_atual_em_limiares"], r["forca_anterior_em_limiares"])

    def test_delta_de_forca_obrigatorio(self):
        for v in (0, -1, True, 101):
            with self.subTest(v=v):
                with self.assertRaises(ErroTendencia):
                    comparar([100] * 12, mudanca_minima_forca_em_limiares=v)

    def test_janela_menor_que_quatro_bloqueia(self):
        with self.assertRaises(ErroTendencia):
            comparar([100] * 12, janela=3)

    def test_frequencia_incorreta_bloqueia(self):
        with self.assertRaises(ErroTendencia):
            comparar([100] * 12, frequencia="MINUTO")

    def test_nao_declara_probabilidades(self):
        r = comparar([100]*12)
        self.assertEqual(r["orientacao"], "OBSERVADA")
        self.assertIsNone(r["probabilidades_calibradas"])
        self.assertFalse(r["publicavel"])
        self.assertNotIn("valor_projetado", r)


if __name__ == "__main__":
    unittest.main()
