import unittest
from datetime import datetime, timedelta, timezone

from nivon.validacao_tendencias_mercado import (
    ErroBacktestMercado, avaliar_probabilidades_tendencia,
)

BASE = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def instante(t):
    return t.isoformat()


def registro(i, **mudancas):
    emissao = BASE + timedelta(days=i)
    base_ref = emissao - timedelta(hours=2)
    alvo_ref = emissao + timedelta(days=1)
    obj = {
        "serie_id": "CME:SOJA:2026-11:AJUSTE:USC/BU",
        "modelo_versao": "baseline-0.1",
        "regra_rotulagem": "retorno_percentual_banda_1pct",
        "horizonte_sessoes": 1,
        "banda_relativa": "0.01",
        "emitido_em": instante(emissao),
        "treinado_ate": instante(emissao - timedelta(hours=1)),
        "base_referencia_em": instante(base_ref),
        "base_disponivel_em": instante(emissao - timedelta(hours=1)),
        "alvo_referencia_em": instante(alvo_ref),
        "alvo_disponivel_em": instante(alvo_ref + timedelta(hours=1)),
        "valor_base": "100",
        "valor_alvo": "102",
        "classe_realizada": "ALTA",
        "edicao_real_sha256": "a" * 64,
        "sessao_base": emissao.date().isoformat(),
        "sessao_alvo": alvo_ref.date().isoformat(),
        "probabilidades": {"ALTA": "0.8", "BAIXA": "0.1", "ESTABILIDADE": "0.1"},
    }
    obj.update(mudancas)
    return obj


CORTE = "2026-05-01T12:00:00Z"


def calendario():
    return {
        "mercado": "CME", "fonte_id": "TESTE-CAL",
        "edicao_sha256": "b" * 64,
        "publicacao_em": "2025-12-01T09:00:00Z",
        "coleta_em": "2025-12-01T10:00:00Z",
        "sessoes": [(BASE + timedelta(days=i)).date().isoformat()
                    for i in range(75)],
    }


class TestBacktestTendenciasMercados(unittest.TestCase):
    def test_brier_sem_chamar_calibrado(self):
        dados = [registro(i) for i in range(65)]
        r = avaliar_probabilidades_tendencia(dados, as_of=CORTE, calendario_sessoes=calendario())
        self.assertEqual(r["status"], "BACKTEST_TEMPORAL_OFFLINE_NAO_HOMOLOGADO")
        self.assertEqual(r["avaliacoes"], 44)
        self.assertAlmostEqual(r["brier_multiclasse"], 0.06)
        self.assertFalse(r["publicavel"])
        self.assertIsNone(r["probabilidades_calibradas"])
        self.assertLess(r["skill_brier_vs_benchmark"], 0)

    def test_amostra_pequena_nao_validada(self):
        r = avaliar_probabilidades_tendencia([registro(i) for i in range(10)],
                                              as_of=CORTE, calendario_sessoes=calendario())
        self.assertEqual(r["status"], "AMOSTRA_INSUFICIENTE")

    def test_captura_do_alvo_depois_da_emissao(self):
        dados = [registro(i) for i in range(65)]
        dados[5]["alvo_disponivel_em"] = dados[5]["emitido_em"]
        with self.assertRaisesRegex(ErroBacktestMercado, "look-ahead"):
            avaliar_probabilidades_tendencia(dados, as_of=CORTE, calendario_sessoes=calendario())

    def test_treino_depois_da_emissao(self):
        dados = [registro(i) for i in range(65)]
        dados[4]["treinado_ate"] = dados[4]["alvo_disponivel_em"]
        with self.assertRaises(ErroBacktestMercado):
            avaliar_probabilidades_tendencia(dados, as_of=CORTE, calendario_sessoes=calendario())

    def test_classe_nao_bate_com_preco(self):
        dados = [registro(i) for i in range(65)]
        dados[7]["classe_realizada"] = "ESTABILIDADE"
        with self.assertRaisesRegex(ErroBacktestMercado, "inconsistente"):
            avaliar_probabilidades_tendencia(dados, as_of=CORTE, calendario_sessoes=calendario())

    def test_soma_probabilidade_invalida(self):
        dados = [registro(i) for i in range(65)]
        dados[6]["probabilidades"] = {"ALTA": "0.8", "BAIXA": "0.8",
                                       "ESTABILIDADE": "0.1"}
        with self.assertRaisesRegex(ErroBacktestMercado, "somam"):
            avaliar_probabilidades_tendencia(dados, as_of=CORTE, calendario_sessoes=calendario())

    def test_mercados_ou_vencimentos_diferentes(self):
        dados = [registro(i) for i in range(65)]
        dados[3]["serie_id"] = "CME:SOJA:2027-01:AJUSTE:USC/BU"
        with self.assertRaisesRegex(ErroBacktestMercado, "mistura"):
            avaliar_probabilidades_tendencia(dados, as_of=CORTE, calendario_sessoes=calendario())

    def test_duplicacao_origem_alvo(self):
        dados = [registro(i) for i in range(65)]
        dados.append(dict(dados[8]))
        with self.assertRaisesRegex(ErroBacktestMercado, "duplicada"):
            avaliar_probabilidades_tendencia(dados, as_of=CORTE, calendario_sessoes=calendario())

    def test_futuro_depois_do_corte(self):
        dados = [registro(i) for i in range(65)]
        dados[8]["alvo_disponivel_em"] = "2026-06-01T12:00:00Z"
        with self.assertRaisesRegex(ErroBacktestMercado, "look-ahead"):
            avaliar_probabilidades_tendencia(dados, as_of=CORTE, calendario_sessoes=calendario())

    def test_sem_fuso_bloqueia(self):
        dados = [registro(i) for i in range(65)]
        dados[8]["emitido_em"] = "2026-01-09T12:00:00"
        with self.assertRaisesRegex(ErroBacktestMercado, "fuso"):
            avaliar_probabilidades_tendencia(dados, as_of=CORTE, calendario_sessoes=calendario())

    def test_sem_calendario_nao_atesta_skill(self):
        r = avaliar_probabilidades_tendencia(
            [registro(i) for i in range(65)], as_of=CORTE)
        self.assertEqual(r["status"], "HORIZONTE_CALENDARIO_AUSENTE")
        self.assertEqual(r["avaliacoes"], 0)

    def test_horizonte_falso_em_toda_serie_bloqueia(self):
        dados = [registro(i, horizonte_sessoes=2) for i in range(65)]
        with self.assertRaisesRegex(ErroBacktestMercado, "horizonte_sessoes"):
            avaliar_probabilidades_tendencia(
                dados, as_of=CORTE, calendario_sessoes=calendario())

    def test_sessao_de_mercado_omitida_nao_e_pregao_consecutivo(self):
        dados = [registro(i) for i in range(65)]
        cal = calendario()
        cal["sessoes"].remove("2026-01-10")
        with self.assertRaisesRegex(ErroBacktestMercado, "horizonte_sessoes"):
            avaliar_probabilidades_tendencia(
                dados, as_of=CORTE, calendario_sessoes=cal)

    def test_rotulo_sessao_tem_de_conferir_com_referencia_local(self):
        dados = [registro(i) for i in range(65)]
        dados[8]["sessao_base"] = "2026-01-01"
        with self.assertRaisesRegex(ErroBacktestMercado, "sessão divergente"):
            avaliar_probabilidades_tendencia(
                dados, as_of=CORTE, calendario_sessoes=calendario())

    def test_limiar_em_relacao_ao_preco(self):
        dados = [registro(i) for i in range(65)]
        dados[8]["valor_alvo"] = "100.9"
        dados[8]["classe_realizada"] = "ESTABILIDADE"
        with self.assertRaisesRegex(ErroBacktestMercado, "mistura"):
            # A banda continua única, mas a classe correta de um registro pode
            # diferir. O gate de mistura é ativado apenas por versão/limiar.
            dados[8]["banda_relativa"] = "0.02"
            avaliar_probabilidades_tendencia(dados, as_of=CORTE, calendario_sessoes=calendario())


if __name__ == "__main__":
    unittest.main()
