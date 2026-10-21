"""Contrato E2E offline: PR #21 validator real -> PR #20 Brier normalizer.

Somente dados sintéticos. É integração de código, NÃO prova de vintages,
origem, calendário oficial, skill real, licença ou calibração.
"""
from datetime import datetime, timedelta, timezone
import unittest

from nivon.integracao_contratos_quant import normalizar_relatorio_brier_mercados
from nivon.quant_core import ErroQuantitativo, avaliar_previsoes_oos
from nivon.validacao_tendencias_mercado import (
    ErroBacktestMercado, avaliar_probabilidades_tendencia,
)

BASE = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
CORTE = "2026-05-01T12:00:00Z"
SERIE = "CME:SOJA:2026-11:AJUSTE:USC/BU"
CLASSES = ("ALTA", "BAIXA", "ESTABILIDADE")


def iso(dt):
    return dt.isoformat()


def fixture(n=65):
    """Mesmo arquivo sintético normalizado para os dois contratos."""
    datas = [(BASE + timedelta(days=i)).date().isoformat() for i in range(80)]
    calendario = {
        "mercado": "CME", "fonte_id": "CALENDARIO_TESTE_DECLARADO",
        "edicao_sha256": "a" * 64,
        "publicacao_em": "2025-12-01T09:00:00Z",
        "coleta_em": "2025-12-01T10:00:00Z",
        "sessoes": datas,
    }
    mercado, quant = [], []
    for i in range(n):
        origem = BASE + timedelta(days=i)
        alvo = origem + timedelta(days=1)
        classe = CLASSES[i % 3]
        preco = {"ALTA": 102.0, "BAIXA": 98.0, "ESTABILIDADE": 100.0}[classe]
        probs = {c: 0.8 if c == classe else 0.1 for c in CLASSES}
        base_disp = origem - timedelta(hours=1)
        alvo_disp = alvo + timedelta(hours=1)
        mercado.append({
            "serie_id": SERIE, "modelo_versao": "fixture-e2e-v1",
            "regra_rotulagem": "retorno_percentual_banda_1pct",
            "horizonte_sessoes": 1, "banda_relativa": "0.01",
            "emitido_em": iso(origem),
            "treinado_ate": iso(base_disp),
            "base_referencia_em": iso(origem - timedelta(hours=2)),
            "base_disponivel_em": iso(base_disp),
            "alvo_referencia_em": iso(alvo),
            "alvo_disponivel_em": iso(alvo_disp),
            "valor_base": "100", "valor_alvo": str(preco),
            "classe_realizada": classe,
            "edicao_real_sha256": "b" * 64,
            "sessao_base": origem.date().isoformat(),
            "sessao_alvo": alvo.date().isoformat(),
            "probabilidades": {c: str(probs[c]) for c in CLASSES},
        })
        quant.append({
            "serie_id": SERIE, "modelo_id": "fixture-e2e-v1",
            "unidade": "USC/BU", "baseline_id": "PERSISTENCIA",
            "horizonte_periodos": 1,
            "periodo_origem": origem.date().isoformat(),
            "alvo_periodo": alvo.date().isoformat(),
            "emitido_em": iso(origem),
            "dados_disponiveis_ate": iso(base_disp),
            "treino_disponivel_ate": iso(base_disp),
            "observado_publicado_em": iso(alvo),
            "observado_coletado_em": iso(alvo_disp),
            "edicao_sha256": "b" * 64,
            "valor_base": 100.0, "baseline": 100.0,
            "previsto": preco, "real": preco,
            "probabilidades": probs,
        })
    return calendario, mercado, quant


class TestInteroperabilidadeMercadoQuantE2E(unittest.TestCase):
    def test_prequential_real_converte_score_sem_confundir_escala(self):
        calendario, mercado, quant = fixture()
        from_mercados = avaliar_probabilidades_tendencia(
            mercado, as_of=CORTE, calendario_sessoes=calendario
        )
        normalizado = normalizar_relatorio_brier_mercados(from_mercados)
        from_quant = avaliar_previsoes_oos(
            quant, calendario=calendario["sessoes"], serie_id=SERIE,
            modelo_id="fixture-e2e-v1", unidade="USC/BU",
            baseline_id="PERSISTENCIA", horizonte_periodos=1,
            as_of_avaliacao=CORTE, min_folds=30,
            tolerancia_relativa=0.01,
        )
        self.assertEqual(
            from_mercados["status"], "BACKTEST_TEMPORAL_OFFLINE_NAO_HOMOLOGADO")
        self.assertEqual(normalizado["n_folds"], from_mercados["avaliacoes"])
        self.assertEqual(from_mercados["amostra_total"], 65)
        self.assertEqual(from_mercados["avaliacoes"], 44)
        self.assertEqual(from_quant["n_folds"], 65)
        # Perda por linha identica; PR #21 usa soma (0.06), Quant soma/3 (0.02).
        self.assertAlmostEqual(from_mercados["brier_multiclasse"], 0.06)
        self.assertAlmostEqual(normalizado["brier_multiclasse_medio"], 0.02)
        self.assertAlmostEqual(
            normalizado["brier_multiclasse_medio"],
            from_quant["brier_multiclasse_medio"])
        self.assertAlmostEqual(
            normalizado["brier_soma_tres_classes"],
            3 * normalizado["brier_multiclasse_medio"])
        self.assertAlmostEqual(
            normalizado["skill_brier_vs_benchmark"],
            from_mercados["skill_brier_vs_benchmark"])
        self.assertEqual(
            normalizado["cobertura_calendario_declarada"]["edicao_sha256"],
            calendario["edicao_sha256"])
        self.assertFalse(
            normalizado["cobertura_calendario_declarada"]["calendario_oficial_comprovado"])
        self.assertFalse(normalizado["calibracao_verificada"])
        self.assertIsNone(normalizado["probabilidades_calibradas"])
        self.assertFalse(normalizado["publicavel"])
        self.assertFalse(from_mercados["publicavel"])
        self.assertFalse(from_quant["publicavel"])

    def test_sem_calendario_mercados_nao_pode_ser_normalizado(self):
        _, previsoes, _ = fixture()
        resultado = avaliar_probabilidades_tendencia(
            previsoes, as_of=CORTE, calendario_sessoes=None
        )
        self.assertEqual(resultado["status"], "HORIZONTE_CALENDARIO_AUSENTE")
        with self.assertRaises(ErroQuantitativo):
            normalizar_relatorio_brier_mercados(resultado)

    def test_sessao_omitida_bloqueia_na_origem_e_nao_gera_score(self):
        cal, previsoes, _ = fixture()
        cal["sessoes"].remove("2026-01-10")
        with self.assertRaises(ErroBacktestMercado):
            avaliar_probabilidades_tendencia(
                previsoes, as_of=CORTE, calendario_sessoes=cal
            )

    def test_classes_por_preco_divergentes_bloqueiam_antes_do_bridge(self):
        cal, previsoes, _ = fixture()
        previsoes[12]["classe_realizada"] = "BAIXA"
        with self.assertRaisesRegex(ErroBacktestMercado, "inconsistente"):
            avaliar_probabilidades_tendencia(
                previsoes, as_of=CORTE, calendario_sessoes=cal
            )

    def test_brier_adulterado_no_transporte_reprovado(self):
        cal, previsoes, _ = fixture()
        resultado = avaliar_probabilidades_tendencia(
            previsoes, as_of=CORTE, calendario_sessoes=cal
        )
        resultado["skill_brier_vs_benchmark"] += 0.1
        with self.assertRaisesRegex(ErroQuantitativo, "skill"):
            normalizar_relatorio_brier_mercados(resultado)

    def test_historico_sem_maturacao_minima_nao_simula_backtest(self):
        cal, previsoes, _ = fixture(n=10)
        resultado = avaliar_probabilidades_tendencia(
            previsoes, as_of=CORTE, calendario_sessoes=cal
        )
        self.assertEqual(resultado["status"], "AMOSTRA_INSUFICIENTE")
        self.assertFalse(resultado["publicavel"])
        with self.assertRaises(ErroQuantitativo):
            normalizar_relatorio_brier_mercados(resultado)


if __name__ == "__main__":
    unittest.main()
