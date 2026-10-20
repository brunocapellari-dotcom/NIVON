"""Teste sintético do IVO: aprendizado de pesos com corte estrito de publicação/coleta."""
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from nivon.historico import Observacao
from nivon.ivo_lab_temporal import ErroLab, prever_asof, walkforward_asof

UTC = timezone.utc


def mes_mais_um(ano, mes):
    return (ano + int(mes == 12), mes % 12 + 1)


def serie(ano_inicio=2018, ano_final=2025):
    dados = []
    for ano in range(ano_inicio, ano_final+1):
        for mes in range(1, 13):
            proximo_ano, proximo_mes = mes_mais_um(ano, mes)
            publicacao = date(proximo_ano, proximo_mes, 4)
            coleta = datetime(proximo_ano, proximo_mes, 5, 12, tzinfo=UTC)
            # Sazonalidade + tendência: números sintéticos sem realidade agrícola.
            valor = 200. + 5*(ano-ano_inicio) + mes*7
            dados.append(Observacao(
                fonte="CONAB", variavel="PRODUCAO", produto="SOJA", regiao="MT",
                unidade="t", competencia=f"{ano}-{mes:02d}",
                calendario="MENSAL", referencia=date(ano, mes, 1),
                publicacao=publicacao, coleta=coleta, valor=valor,
                natureza="OBSERVADO", edicao="primeira"))
    return dados


def prever(obs, alvo="2024-07", **kwargs):
    return prever_asof(obs, periodo_alvo=alvo,
                       fonte="CONAB", variavel="PRODUCAO", produto="SOJA",
                       regiao="MT", unidade="t", **kwargs)


def backtest(obs, **kwargs):
    return walkforward_asof(obs, fonte="CONAB", variavel="PRODUCAO",
                            produto="SOJA", regiao="MT", unidade="t",
                            inicio="2024-01", fim="2024-12", **kwargs)


class TestIVOLabTemporal(unittest.TestCase):
    def test_treina_peso_restrito_e_snapshot_verificavel(self):
        p = prever(serie())
        self.assertEqual(p["estado"], "CANDIDATO_NAO_HOMOLOGADO")
        self.assertGreaterEqual(p["treino"]["amostras_treino"], 6)
        self.assertGreaterEqual(p["treino"]["peso_recente"], 0.)
        self.assertLessEqual(p["treino"]["peso_recente"], 1.)
        self.assertFalse(p["modelo_homologado"])
        self.assertEqual(len(p["checksum_evidencia"]), 64)
        self.assertEqual(p["features_asof"]["sazonal_periodo"], "2023-07")
        # Junho 2024 só é publicado em julho e deve ser excluído do corte
        self.assertEqual(p["features_asof"]["ultimo_periodo"], "2024-05")

    def test_revisao_futura_nao_muda_previsao_historica(self):
        original = serie()
        p1 = prever(original)
        alvo = next(x for x in original if x.competencia == "2024-05")
        revisao = replace(
            alvo, valor=90000., edicao="posterior",
            publicacao=date(2024, 9, 4),
            coleta=datetime(2024, 9, 5, tzinfo=UTC))
        p2 = prever(original + [revisao])
        self.assertEqual(p1["previsao"], p2["previsao"])
        self.assertEqual(p1["checksum_evidencia"], p2["checksum_evidencia"])

    def test_backfill_tardio_nao_finge_dado_disponivel_na_epoca(self):
        updated = [
            replace(x, coleta=datetime(2026, 2, 5, tzinfo=UTC))
            for x in serie(2018, 2024)
        ]
        with self.assertRaises(ErroLab):
            prever(updated)

    def test_projecao_e_calendario_diferente_rejeitados(self):
        dados = serie()
        for novo in (replace(dados[0], natureza="PROJETADO"),
                     replace(dados[0], calendario="SAFRA")):
            with self.assertRaises(ErroLab):
                prever([novo] + dados[1:])

    def test_dados_alheios_ignorados_sem_contaminar(self):
        original = serie()
        estranho = replace(original[0], produto="MILHO", valor=1000000.)
        self.assertEqual(prever(original)["previsao"],
                         prever(original+[estranho])["previsao"])

    def test_backtest_walkforward_sem_promocao(self):
        a = backtest(serie())
        self.assertEqual(a["folds_validos"], 12)
        self.assertEqual(len(a["folds"]), 12)
        self.assertFalse(a["promocao_automatica"])
        self.assertEqual(a["estado"], "BACKTEST_OFFLINE_NAO_HOMOLOGADO")
        self.assertIsNotNone(a["mae_modelo"])
        self.assertIsNotNone(a["mae_baseline"])
        self.assertEqual(a["folds"][0]["periodo"], "2024-01")
        self.assertGreaterEqual(a["folds"][0]["treino_amostras"], 6)

    def test_sem_rotulo_publicado_nao_avalie(self):
        s = [x for x in serie() if x.competencia != "2024-12"]
        a = backtest(s)
        self.assertEqual(a["folds_validos"], 11)
        self.assertTrue(any(x["periodo"] == "2024-12" for x in a["ignorados"]))

    def test_periodo_invalido(self):
        for mes in ("2024-13", "24-01", "2024-1", "2024/01", "", "2024-00"):
            with self.subTest(mes=mes):
                with self.assertRaises(ErroLab):
                    prever(serie(), alvo=mes)

    def test_regularizacao_ou_amostra_invalida(self):
        for extras in ({"minimo_treino": 2}, {"minimo_treino": True},
                       {"regularizacao": -0.01}, {"regularizacao": float("nan")},
                       {"regularizacao": True}):
            with self.subTest(kwargs=extras):
                with self.assertRaises(ErroLab):
                    prever(serie(), **extras)

    def test_publicacao_future_deliberada_nao_serve_como_feature(self):
        dados = serie()
        alvo = next(x for x in dados if x.competencia == "2023-07")
        alterado = replace(alvo, publicacao=date(2024, 12, 10),
                           coleta=datetime(2024, 12, 11, tzinfo=UTC))
        # Em julho/2024, a observação sazonal de julho/2023 foi adiada
        # para publicação em dezembro/2024. O cálculo precisa falhar fechado.
        with self.assertRaises(ErroLab):
            prever([x for x in dados if x is not alvo] + [alterado])


if __name__ == "__main__":
    unittest.main()
