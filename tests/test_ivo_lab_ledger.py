"""E2E de treino as-of -> replay em SQLite -> avaliação persistida."""
import unittest
from datetime import date, datetime, timezone

from nivon.historico import Observacao
from nivon.ivo_lab_temporal import walkforward_asof
from nivon.ivo_lab_ledger import arquivar_replay_sintetico
from nivon.ivo_previsao_ledger import LedgerPrevisoes, ErroLedger


def serie():
    obs=[]
    for year in range(2019,2025):
        for month in range(1,13):
            py = year + (month == 12)
            pm = month % 12 + 1
            obs.append(Observacao(
                fonte="CONAB", variavel="PRODUCAO", produto="SOJA",
                regiao="MT", unidade="t", competencia=f"{year}-{month:02d}",
                calendario="MENSAL", referencia=date(year,month,1),
                publicacao=date(py,pm,4),
                coleta=datetime(py,pm,5,tzinfo=timezone.utc),
                valor=float(100+month*3+(year-2019)*2)))
    return obs


def previsoes():
    return walkforward_asof(
        serie(), fonte="CONAB", variavel="PRODUCAO", produto="SOJA",
        regiao="MT", unidade="t", inicio="2023-01", fim="2023-12")


class TestIVOReplayPersistido(unittest.TestCase):
    def test_pipeline_asof_treina_salva_e_avalia(self):
        r=previsoes()
        self.assertEqual(r["folds_validos"],12)
        led=LedgerPrevisoes()
        try:
            with self.assertRaises(PermissionError):
                arquivar_replay_sintetico(r,ledger=led)
            with self.assertRaises(PermissionError):
                arquivar_replay_sintetico(r,ledger=led,autorizado=True)
            imp=arquivar_replay_sintetico(r,ledger=led,autorizado=True,fixture_sintetica_confirmada=True)
            self.assertEqual(imp["previsoes_novas"],12)
            self.assertEqual(imp["observacoes_novas"],12)
            self.assertEqual(imp["modo"],"BACKTEST")
            dados=led.avaliar(
                corte=datetime(2025,1,1,tzinfo=timezone.utc),
                modelo_id="IVO_BLENDED_SEASONAL_SOJA")
            self.assertEqual(dados["avaliadas"],12)
            self.assertTrue(dados["agregacao_comparavel"])
            self.assertAlmostEqual(dados["mae"],r["mae_modelo"])
            self.assertAlmostEqual(dados["mae_baseline"],r["mae_baseline"])
            self.assertFalse(dados["promocao_automatica"])
            segundo=arquivar_replay_sintetico(r,ledger=led,autorizado=True,fixture_sintetica_confirmada=True)
            self.assertEqual(segundo["previsoes_novas"],0)
            self.assertEqual(segundo["observacoes_novas"],0)
            self.assertEqual(led.avaliar(
                corte=datetime(2025,1,1,tzinfo=timezone.utc),
                modo="LIVE")["avaliadas"],0)
        finally:led.close()

    def test_relatorio_adulterado_rejeitado_antes_de_escrever(self):
        r=previsoes()
        r["folds"][0]["ultima_coleta_de_features"]="2099-01-01T00:00:00+00:00"
        led=LedgerPrevisoes()
        try:
            with self.assertRaises(ErroLedger):
                arquivar_replay_sintetico(r,ledger=led,autorizado=True,fixture_sintetica_confirmada=True)
            a=led.avaliar(corte=datetime(2025,1,1,tzinfo=timezone.utc))
            self.assertEqual(a["avaliadas"],0)
        finally:led.close()

    def test_duplicacao_fold_rejeitada(self):
        r=previsoes()
        r["folds"].append(dict(r["folds"][0]))
        led=LedgerPrevisoes()
        try:
            with self.assertRaises(ErroLedger):
                arquivar_replay_sintetico(r,ledger=led,autorizado=True,fixture_sintetica_confirmada=True)
        finally:led.close()

    def test_replay_nao_pode_se_prometer_homologado(self):
        r=previsoes()
        r["promocao_automatica"]=True
        led=LedgerPrevisoes()
        try:
            with self.assertRaises(ErroLedger):
                arquivar_replay_sintetico(r,ledger=led,autorizado=True,fixture_sintetica_confirmada=True)
        finally:led.close()


if __name__=="__main__":
    unittest.main()
