import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from nivon.ivo_previsao_ledger import (
    ErroLedger, LedgerPrevisoes, ObservacaoPublicada, PrevisaoRegistrada,
)

UTC = timezone.utc
HASH = sha256(b"fixture-sintetica").hexdigest()


def instante(ano, mes, dia):
    return datetime(ano, mes, dia, 12, tzinfo=UTC)


def previsao(id="p1", periodo="2026-01", **kw):
    d = dict(
        id=id, modelo_id="SOJA_MT", versao_modelo="v1",
        indicador="PRODUCAO", geografia="MT", unidade="t",
        periodo=periodo, fonte_verdade="CONAB",
        emitida_em=instante(2025, 12, 15),
        disponivel_ate=instante(2025, 12, 14),
        registrada_em=instante(2025, 12, 16),
        estimativa=102.0, baseline=120.0, evidencia_sha256=HASH,
        limite_inferior=90.0, limite_superior=110.0,
    )
    d.update(kw)
    return PrevisaoRegistrada(**d)


def obs(id="o1", periodo="2026-01", publicado=None, valor=100, **kw):
    d = dict(id=id, fonte_id="CONAB", indicador="PRODUCAO", geografia="MT",
             unidade="t", periodo=periodo,
             publicada_em=publicado or instante(2026, 2, 3),
             registrada_em=instante(2026, 2, 4), valor=valor,
             evidencia_sha256=HASH)
    d.update(kw)
    return ObservacaoPublicada(**d)


class TestIVOLedger(unittest.TestCase):
    def setUp(self):
        self.db = LedgerPrevisoes()

    def tearDown(self):
        self.db.close()

    def test_previsao_e_observacao_idempotentes(self):
        self.assertEqual(self.db.registrar_previsao(previsao()), "REGISTRADO")
        self.assertEqual(self.db.registrar_previsao(previsao()), "IDEMPOTENTE")
        self.assertEqual(self.db.registrar_observacao(obs()), "REGISTRADO")
        self.assertEqual(self.db.registrar_observacao(obs()), "IDEMPOTENTE")

    def test_revisao_nao_sobrescreve_versao_anterior(self):
        self.db.registrar_previsao(previsao())
        self.db.registrar_observacao(obs())
        self.db.registrar_observacao(obs(
            "o2", publicado=instante(2026, 3, 4),
            registrada_em=instante(2026, 3, 5), valor=110))
        cutoff = instante(2026, 3, 10)
        a = self.db.avaliar(corte=cutoff)
        b = self.db.avaliar(corte=cutoff, verdade="ULTIMA_ATE_CORTE")
        self.assertEqual(a["avaliacoes"][0]["observado"], 100)
        self.assertEqual(b["avaliacoes"][0]["observado"], 110)
        self.assertEqual(a["avaliacoes"][0]["observacao_id"], "o1")

    def test_vintage_futura_nao_vaza_ao_backtest(self):
        self.db.registrar_previsao(previsao())
        self.db.registrar_observacao(obs())
        self.db.registrar_observacao(obs("o2", publicado=instante(2026, 3, 4),
            registrada_em=instante(2026, 3, 5), valor=200))
        x = self.db.avaliar(corte=instante(2026, 2, 10), verdade="ULTIMA_ATE_CORTE")
        self.assertEqual(x["avaliacoes"][0]["observado"], 100)

    def test_metricas_e_intervalos(self):
        self.db.registrar_previsao(previsao())
        self.db.registrar_observacao(obs())
        a = self.db.avaliar(corte=instante(2026, 2, 10))
        self.assertEqual(a["avaliadas"], 1)
        self.assertAlmostEqual(a["mae"], 2.0)
        self.assertAlmostEqual(a["wape"], .02)
        self.assertAlmostEqual(a["mae_baseline"], 20.0)
        self.assertAlmostEqual(a["ganho_relativo_baseline"], .9)
        self.assertEqual(a["vies_medio"], 2.0)
        self.assertEqual(a["cobertura_intervalo"], 1.0)
        self.assertFalse(a["promocao_automatica"])

    def test_previsao_nao_observada_conta_pendente(self):
        self.db.registrar_previsao(previsao())
        a = self.db.avaliar(corte=instante(2026, 2, 10))
        self.assertEqual(a["avaliadas"], 0)
        self.assertEqual(a["sem_observacao"], 1)
        self.assertIsNone(a["mae"])

    def test_previsao_registrada_apos_corte_nao_e_visivel(self):
        self.db.registrar_previsao(previsao())
        a = self.db.avaliar(corte=instante(2025, 12, 15))
        self.assertEqual(a["sem_observacao"], 0)

    def test_proibe_alterar_previsao_ja_registrada(self):
        self.db.registrar_previsao(previsao())
        with self.assertRaises(ErroLedger):
            self.db.registrar_previsao(previsao(estimativa=999))

    def test_proibe_alterar_observacao_ja_registrada(self):
        self.db.registrar_observacao(obs())
        with self.assertRaises(ErroLedger):
            self.db.registrar_observacao(obs(valor=999))

    def test_impede_previsao_emitida_no_mes_alvo(self):
        with self.assertRaises(ErroLedger):
            self.db.registrar_previsao(previsao(emitida_em=instante(2026, 1, 2),
                                               registrada_em=instante(2026, 1, 2)))

    def test_impede_antecipar_verdade_no_corte(self):
        with self.assertRaises(ErroLedger):
            self.db.registrar_previsao(previsao(
                disponivel_ate=instante(2025, 12, 25)))

    def test_impede_live_registrado_tarde(self):
        with self.assertRaises(ErroLedger):
            self.db.registrar_previsao(previsao(modo="LIVE",
                                                registrada_em=instante(2026, 2, 2)))

    def test_observacao_mensal_antes_do_fechamento_rejeitada(self):
        with self.assertRaises(ErroLedger):
            self.db.registrar_observacao(obs(publicado=instante(2026, 1, 20)))

    def test_bloqueia_intervalo_incompleto_e_invalido(self):
        for alteracao in ({"limite_inferior": None}, {"limite_inferior": 120},
                          {"limite_superior": 101}):
            with self.subTest(alteracao=alteracao):
                with self.assertRaises(ErroLedger):
                    self.db.registrar_previsao(previsao(**alteracao))

    def test_boolean_nan_inf_rejeitados(self):
        for n in (True, float("nan"), float("inf"), -1.0):
            with self.subTest(n=n):
                with self.assertRaises(ErroLedger):
                    self.db.registrar_previsao(previsao(estimativa=n))

    def test_escopo_fonte_unidade_separa_observacoes(self):
        self.db.registrar_previsao(previsao())
        self.db.registrar_observacao(obs(fonte_id="IMEA"))
        self.db.registrar_observacao(obs(id="o2", unidade="kg"))
        x = self.db.avaliar(corte=instante(2026, 2, 10))
        self.assertEqual(x["avaliadas"], 0)

    def test_persistencia_apos_reabertura(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ivo.db"
            db = LedgerPrevisoes(db_path)
            db.registrar_previsao(previsao())
            db.registrar_observacao(obs())
            db.close()
            db2 = LedgerPrevisoes(db_path)
            self.assertEqual(db2.avaliar(corte=instante(2026, 2, 10))["avaliadas"], 1)
            db2.close()

    def test_vies_sem_denominador_zero_e_sem_intervalo(self):
        self.db.registrar_previsao(previsao(
            estimativa=0., baseline=0., limite_inferior=None, limite_superior=None))
        self.db.registrar_observacao(obs(valor=0.))
        x = self.db.avaliar(corte=instante(2026, 2, 10))
        self.assertIsNone(x["wape"])
        self.assertIsNone(x["ganho_relativo_baseline"])
        self.assertIsNone(x["cobertura_intervalo"])

    def test_live_e_backtest_nao_se_misturam(self):
        self.db.registrar_previsao(previsao())
        self.db.registrar_observacao(obs())
        x = self.db.avaliar(corte=instante(2026, 2, 10), modo="LIVE")
        self.assertEqual(x["avaliadas"], 0)


if __name__ == "__main__":
    unittest.main()
