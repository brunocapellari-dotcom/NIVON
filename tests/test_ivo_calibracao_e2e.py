"""IVO: experimento E2E estritamente sintético de treino -> ledger -> intervalo."""
import unittest
from datetime import date, datetime, timezone
from hashlib import sha256

from nivon.historico import Observacao
from nivon.ivo_intervalos import intervalo_empirico_asof
from nivon.ivo_lab_ledger import arquivar_replay_sintetico
from nivon.ivo_lab_temporal import walkforward_asof
from nivon.ivo_previsao_ledger import LedgerPrevisoes, PrevisaoRegistrada

UTC = timezone.utc
H=sha256(b"ivo-e2e-calibracao-fixture").hexdigest()


def serie_sintetica():
    dados = []
    for ano in range(2018, 2025):
        for mes in range(1, 13):
            aa = ano + int(mes == 12)
            mm = mes % 12 + 1
            dados.append(Observacao(
                fonte="CONAB", variavel="PRODUCAO", produto="SOJA",
                regiao="MT", unidade="t", competencia=f"{ano}-{mes:02d}",
                calendario="MENSAL", referencia=date(ano, mes, 1),
                publicacao=date(aa, mm, 3),
                coleta=datetime(aa, mm, 4, 12, tzinfo=UTC),
                valor=80. + 0.7*(ano-2018) + 2.2*mes + (mes%3)))
    return dados


class TestIVOCalibracaoE2E(unittest.TestCase):
    def test_treino_backtest_ledger_intervalo_sem_autopromocao(self):
        relatorio=walkforward_asof(
            serie_sintetica(), fonte="CONAB", variavel="PRODUCAO",
            produto="SOJA", regiao="MT", unidade="t",
            inicio="2023-01", fim="2023-12")
        self.assertEqual(relatorio["folds_validos"],12)
        ledger=LedgerPrevisoes()
        try:
            salvo=arquivar_replay_sintetico(
                relatorio, ledger=ledger, autorizado=True,
                fixture_sintetica_confirmada=True)
            self.assertEqual(salvo["previsoes_novas"],12)
            serie=ledger.avaliar(
                corte=datetime(2025, 1, 1, tzinfo=UTC),
                modo="BACKTEST", verdade="PRIMEIRA_PUBLICACAO",
                modelo_id="IVO_BLENDED_SEASONAL_SOJA")
            self.assertEqual(serie["avaliadas"],12)
            alvo=PrevisaoRegistrada(
                id="alvo-2024-08", modelo_id="IVO_BLENDED_SEASONAL_SOJA",
                versao_modelo="LAB_V1", indicador="PRODUCAO", geografia="MT",
                unidade="t", periodo="2024-08", fonte_verdade="CONAB",
                emitida_em=datetime(2024, 7, 14, tzinfo=UTC),
                disponivel_ate=datetime(2024, 7, 13, tzinfo=UTC),
                registrada_em=datetime(2024, 7, 15, tzinfo=UTC),
                estimativa=106., baseline=110., evidencia_sha256=H,
                modo="BACKTEST")
            faixa=intervalo_empirico_asof(alvo, serie, confianca_nominal=.8)
            self.assertEqual(faixa["status"], "INTERVALO_EXPERIMENTAL_NAO_HOMOLOGADO")
            self.assertEqual(faixa["candidatos_elegiveis"], 12)
            self.assertLessEqual(faixa["limite_inferior"], 106.)
            self.assertGreaterEqual(faixa["limite_superior"], 106.)
            self.assertFalse(faixa["intervalo_homologado"])
            self.assertFalse(faixa["promocao_automatica"])
        finally:
            ledger.close()


if __name__=="__main__":
    unittest.main()
