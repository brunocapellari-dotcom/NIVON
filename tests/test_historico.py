import unittest
from dataclasses import replace
from datetime import date, datetime, timezone

from nivon.historico import ErroHistorico, Observacao, serie_anual, visao_na_data


def dt(y, m, d):
    return datetime(y, m, d, 12, tzinfo=timezone.utc)


class TestHistoricoAsOf(unittest.TestCase):
    def obs(self, *, ano="2024", valor=100.0, publicacao=date(2025, 1, 20),
            coleta=dt(2025, 1, 21), fonte="SINTETICA"):
        return Observacao(fonte, "CONSUMO_INTERNO", "MILHO", "BR",
                          "TONELADAS", ano, "ANO_CIVIL",
                          date(int(ano), 12, 31), publicacao, coleta, valor)

    def test_versao_futura_nao_contamina_backtest(self):
        inicial = self.obs(valor=100.0)
        rev = self.obs(valor=110.0, publicacao=date(2025, 5, 5), coleta=dt(2025, 5, 6))
        old = visao_na_data([rev, inicial], data_corte_publicacao=date(2025, 2, 1),
                            instante_corte_coleta=dt(2025, 2, 2))
        self.assertEqual([o.valor for o in old], [100.0])
        new = visao_na_data([inicial, rev], data_corte_publicacao=date(2025, 6, 1),
                            instante_corte_coleta=dt(2025, 6, 2))
        self.assertEqual([o.valor for o in new], [110.0])

    def test_fonte_distinta_nao_sobrescreve(self):
        x = visao_na_data([self.obs(fonte="A"), self.obs(fonte="B", valor=99)],
                          data_corte_publicacao=date(2025, 2, 1),
                          instante_corte_coleta=dt(2025, 2, 2))
        self.assertEqual(len(x), 2)

    def test_versoes_mesmo_dia_ainda_respeitam_coleta(self):
        inicial = self.obs(valor=100)
        posterior = self.obs(valor=105, coleta=dt(2025, 1, 22))
        x = visao_na_data([posterior, inicial],
                          data_corte_publicacao=date(2025, 1, 23),
                          instante_corte_coleta=dt(2025, 1, 21))
        self.assertEqual(x[0].valor, 100)

    def test_carimbos_identicos_com_valores_distintos_falham(self):
        with self.assertRaises(ErroHistorico):
            visao_na_data([self.obs(valor=100), self.obs(valor=101)],
                          data_corte_publicacao=date(2025, 3, 1),
                          instante_corte_coleta=dt(2025, 3, 2))

    def test_serie_anual_observada_com_filtro_exato(self):
        xs = [self.obs(ano="2023", valor=70, publicacao=date(2024, 1, 3),
                       coleta=dt(2024, 1, 4)), self.obs(ano="2024", valor=72)]
        s = serie_anual(xs, variavel="CONSUMO_INTERNO", produto="MILHO",
                        regiao="BR", fonte="SINTETICA", unidade="TONELADAS")
        self.assertEqual(s, {2023: 70.0, 2024: 72.0})

    def test_projecao_nao_entra_como_observado(self):
        with self.assertRaises(ErroHistorico):
            serie_anual([replace(self.obs(), natureza="PROJETADO")],
                        variavel="CONSUMO_INTERNO", produto="MILHO",
                        regiao="BR", fonte="SINTETICA", unidade="TONELADAS")

    def test_coleta_anterior_publicacao_rejeitada(self):
        with self.assertRaises(ErroHistorico):
            self.obs(publicacao=date(2025, 2, 1), coleta=dt(2025, 1, 10))

    def test_data_coleta_sem_timezone_falha(self):
        with self.assertRaises(ErroHistorico):
            self.obs(coleta=datetime(2025, 1, 21, 12))

    def test_referencia_nao_equivale_a_publicacao(self):
        o = self.obs()
        self.assertEqual(o.referencia, date(2024, 12, 31))
        self.assertEqual(o.publicacao, date(2025, 1, 20))


if __name__ == "__main__":
    unittest.main()
