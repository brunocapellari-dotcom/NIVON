"""Testes IVO: conformal empírico com apenas erros conhecidos antes do corte."""
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256

from nivon.ivo_intervalos import intervalo_empirico_asof
from nivon.ivo_previsao_ledger import (
    ErroLedger, LedgerPrevisoes, PrevisaoRegistrada, ObservacaoPublicada,
)

UTC = timezone.utc
H = sha256(b"fixture-calibracao").hexdigest()


def t(y, m, d):
    return datetime(y, m, d, 12, tzinfo=UTC)


def mes_anterior(y, m):
    return (y-1, 12) if m == 1 else (y, m-1)


def mes_seguinte(y, m):
    return (y+1, 1) if m == 12 else (y, m+1)


def montar():
    db = LedgerPrevisoes()
    for ano in (2022, 2023):
        for mes in range(1, 13):
            indice = (ano-2022)*12+mes
            ano_emit, mes_emit = mes_anterior(ano, mes)
            ano_pub, mes_pub = mes_seguinte(ano, mes)
            p = PrevisaoRegistrada(
                id=f"p{indice}", modelo_id="MILHO_MT", versao_modelo="v1",
                indicador="VOLUME", geografia="MT", unidade="t", periodo=f"{ano}-{mes:02d}",
                fonte_verdade="CONAB", emitida_em=t(ano_emit, mes_emit, 14),
                disponivel_ate=t(ano_emit, mes_emit, 13),
                registrada_em=t(ano_emit, mes_emit, 15),
                estimativa=100+indice, baseline=100, evidencia_sha256=H)
            o = ObservacaoPublicada(
                id=f"o{indice}", fonte_id="CONAB", indicador="VOLUME",
                geografia="MT", unidade="t", periodo=f"{ano}-{mes:02d}",
                publicada_em=t(ano_pub,mes_pub,3),
                registrada_em=t(ano_pub,mes_pub,4),
                valor=100., evidencia_sha256=H)
            db.registrar_previsao(p)
            db.registrar_observacao(o)
    alvo = PrevisaoRegistrada(
        id="live-futuro", modelo_id="MILHO_MT", versao_modelo="v1",
        indicador="VOLUME", geografia="MT", unidade="t", periodo="2024-08",
        fonte_verdade="CONAB", emitida_em=t(2024, 7, 14),
        disponivel_ate=t(2024, 7, 13), registrada_em=t(2024, 7, 15),
        estimativa=130, baseline=115, evidencia_sha256=H)
    return db, alvo


class TestIVOIntervalos(unittest.TestCase):
    def setUp(self):
        self.db, self.alvo = montar()
        self.aval = self.db.avaliar(corte=t(2025, 1, 1))

    def tearDown(self):
        self.db.close()

    def test_quantil_conservador_e_intervalo_nao_homologado(self):
        x = intervalo_empirico_asof(self.alvo, self.aval)
        self.assertEqual(x["status"], "INTERVALO_EXPERIMENTAL_NAO_HOMOLOGADO")
        self.assertEqual(x["candidatos_elegiveis"], 24)
        self.assertEqual(x["quantil_ordem"], 20)
        self.assertEqual(x["raio_erro"], 20.)
        self.assertEqual(x["limite_inferior"], 110.)
        self.assertEqual(x["limite_superior"], 150.)
        self.assertFalse(x["intervalo_homologado"])
        self.assertFalse(x["promocao_automatica"])

    def test_nivel_alto_requer_mais_erros(self):
        x = intervalo_empirico_asof(self.alvo, self.aval, confianca_nominal=.99)
        self.assertEqual(x["status"], "NIVEL_NAO_CALIBRAVEL_COM_AMOSTRA_ATUAL")
        self.assertIsNone(x["limite_superior"])

    def test_aumentar_minimo_gera_status_em_vez_de_chute(self):
        x = intervalo_empirico_asof(self.alvo, self.aval, minimo_folds=30)
        self.assertEqual(x["status"], "AMOSTRA_INSUFICIENTE")
        self.assertIsNone(x["raio_erro"])

    def test_nao_calibra_com_observacao_coletada_apos_emissao(self):
        a = dict(self.aval)
        itens = [dict(v) for v in a["avaliacoes"]]
        itens[0]["observacao_registrada_em"] = t(2024, 9, 1).isoformat()
        a["avaliacoes"] = itens
        x = intervalo_empirico_asof(self.alvo, a)
        self.assertEqual(x["candidatos_elegiveis"], 23)
        self.assertNotIn({"previsao_id":"p1","observacao_id":"o1"}, x["evidencias"])

    def test_nao_calibra_com_publicacao_apos_emissao(self):
        a = dict(self.aval)
        itens = [dict(v) for v in a["avaliacoes"]]
        itens[0]["vintage_publicada_em"] = t(2024, 8, 3).isoformat()
        itens[0]["observacao_registrada_em"] = t(2024, 9, 4).isoformat()
        a["avaliacoes"] = itens
        x = intervalo_empirico_asof(self.alvo, a)
        self.assertEqual(x["candidatos_elegiveis"], 23)

    def test_revisao_futura_nao_pode_ser_fonte_de_calibracao(self):
        with self.assertRaises(ErroLedger):
            intervalo_empirico_asof(
                self.alvo,
                self.db.avaliar(corte=t(2025, 1, 1), verdade="ULTIMA_ATE_CORTE"))

    def test_impede_calibracao_backtest_para_live(self):
        with self.assertRaises(ErroLedger):
            intervalo_empirico_asof(replace(self.alvo, modo="LIVE"), self.aval)

    def test_mistura_unidade_ou_modelo_nao_soma_erros(self):
        p = replace(self.alvo, unidade="kg")
        x = intervalo_empirico_asof(p, self.aval)
        self.assertEqual(x["candidatos_elegiveis"], 0)
        self.assertEqual(x["status"], "AMOSTRA_INSUFICIENTE")

    def test_atualizacao_futura_nao_muda_evidencia(self):
        antes = intervalo_empirico_asof(self.alvo, self.aval)
        novo = ObservacaoPublicada(
            id="revisao-tardia", fonte_id="CONAB", indicador="VOLUME",
            geografia="MT", unidade="t", periodo="2023-12",
            publicada_em=t(2025, 2, 3), registrada_em=t(2025, 2, 4),
            valor=9999., evidencia_sha256=H)
        self.db.registrar_observacao(novo)
        a = self.db.avaliar(corte=t(2025, 3, 1), verdade="PRIMEIRA_PUBLICACAO")
        depois = intervalo_empirico_asof(self.alvo, a)
        self.assertEqual(antes["raio_erro"], depois["raio_erro"])
        self.assertEqual(antes["evidencias"], depois["evidencias"])

    def test_sem_duplicatas_nos_folds(self):
        a = dict(self.aval)
        a["avaliacoes"] = a["avaliacoes"] + [a["avaliacoes"][0]]
        with self.assertRaises(ErroLedger):
            intervalo_empirico_asof(self.alvo, a)

    def test_limites_invalidos(self):
        for opts in ({"confianca_nominal": float("nan")}, {"confianca_nominal": .3},
                     {"confianca_nominal": True}, {"minimo_folds":4},
                     {"max_folds":5}, {"minimo_folds": True}):
            with self.subTest(opts=opts):
                with self.assertRaises(ErroLedger):
                    intervalo_empirico_asof(self.alvo, self.aval, **opts)

    def test_previsao_curtas_raio_maior_que_ponto_nao_fica_negativa(self):
        p = replace(self.alvo, estimativa=5.)
        a = intervalo_empirico_asof(p, self.aval)
        self.assertEqual(a["limite_inferior"], 0.)
        self.assertEqual(a["limite_superior"], 25.)

    def test_horizonte_incompatível_nao_calibra(self):
        p = replace(self.alvo, periodo="2024-09")
        x = intervalo_empirico_asof(p, self.aval)
        self.assertEqual(x["status"], "AMOSTRA_INSUFICIENTE")

    def test_pode_limitar_janela_para_regime_recente(self):
        a = intervalo_empirico_asof(self.alvo, self.aval, max_folds=12)
        self.assertEqual(a["candidatos_elegiveis"], 12)
        self.assertEqual(a["raio_erro"], 23.)  # 11º erro de 12, k=ceil(13*0.8)=11


if __name__ == "__main__":
    unittest.main()
