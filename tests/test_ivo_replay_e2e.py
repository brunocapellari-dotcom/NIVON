"""Fluxo ponta a ponta estritamente sintético: previsão -> publicação -> erro -> alerta."""
import unittest
from datetime import datetime, timezone
from hashlib import sha256

from nivon.ivo_previsao_ledger import LedgerPrevisoes, PrevisaoRegistrada, ObservacaoPublicada
from nivon.ivo_monitor_modelos import diagnosticar_performance

UTC = timezone.utc
HASH = sha256(b"fixture: sem dado real").hexdigest()


class TestIVOReplayE2E(unittest.TestCase):
    def test_nove_meses_com_regimes_de_erro_e_vintages(self):
        db = LedgerPrevisoes()
        try:
            for i in range(1, 10):
                prev_year = 2024 if i == 1 else 2025
                prev_month = 12 if i == 1 else i - 1
                emissao = datetime(prev_year, prev_month, 10, tzinfo=UTC)
                corte = datetime(prev_year, prev_month, 9, tzinfo=UTC)
                registrada = datetime(prev_year, prev_month, 11, tzinfo=UTC)
                real = 100.
                erro = 2 if i <= 6 else 10
                p = PrevisaoRegistrada(
                    id=f"pred-{i}", modelo_id="SAFRA_SOJA_MT", versao_modelo="v1",
                    indicador="PRODUCAO", geografia="MT", unidade="t",
                    periodo=f"2025-{i:02d}", fonte_verdade="CONAB",
                    emitida_em=emissao, disponivel_ate=corte, registrada_em=registrada,
                    estimativa=real+erro, baseline=real+5, evidencia_sha256=HASH,
                    modo="BACKTEST")
                db.registrar_previsao(p)
                final_year = 2026 if i == 12 else 2025
                final_month = (i % 12)+1
                publicado = datetime(final_year, final_month, 4, tzinfo=UTC)
                observado = ObservacaoPublicada(
                    id=f"obs-{i}", fonte_id="CONAB", indicador="PRODUCAO",
                    geografia="MT", unidade="t", periodo=f"2025-{i:02d}",
                    publicada_em=publicado,
                    registrada_em=datetime(final_year, final_month, 5, tzinfo=UTC),
                    valor=real, evidencia_sha256=HASH)
                db.registrar_observacao(observado)
            avaliacao = db.avaliar(corte=datetime(2025, 11, 1, tzinfo=UTC))
            self.assertEqual(avaliacao["avaliadas"], 9)
            self.assertTrue(avaliacao["agregacao_comparavel"])
            self.assertAlmostEqual(avaliacao["mae"], 42./9)
            d = diagnosticar_performance(avaliacao)
            self.assertEqual(d["status"], "ALERTA_DESEMPENHO")
            self.assertTrue(d["aumento_erro"])
            self.assertFalse(d["retreino_automatico"])
            self.assertFalse(d["promocao_automatica"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
