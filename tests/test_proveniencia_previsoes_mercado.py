"""Fixtures 100% sintéticas: integridade relativa, vintages e anti-look-ahead."""
import copy
import unittest

from nivon.proveniencia_previsoes_mercado import (
    ErroRegistroPrevisao, GENESIS, criar_registro_previsao,
    reconciliar_previsao, verificar_cadeia_previsoes,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_E = "d" * 64
CORTE = "2026-10-16T10:00:00Z"


def cotacao(dia, preco, edicao):
    return {
        "mercado": "CME", "produto": "SOJA", "contrato": "2026-11",
        "tipo": "AJUSTE", "unidade": "USC/BU", "instrumento_id": "ZS",
        "data_referencia": dia, "competencia": dia[:7],
        "referencia_em": dia + "T16:00:00-04:00",
        "publicacao_em": dia + "T16:30:00-04:00",
        "coleta_em": dia + "T17:00:00-04:00",
        "fonte_id": "FONTE_SINTETICA",
        "fonte_url": "https://example.org/quotes",
        "edicao_sha256": edicao, "preco": preco,
    }


def previsao():
    return {
        "previsao_id": "TESTE-001",
        "serie_id": "CME:SOJA:2026-11:AJUSTE:USC/BU:ZS",
        "modelo_versao": "synthetic-v1",
        "identidade_economica": [
            "CME", "SOJA", "2026-11", "AJUSTE", "USC/BU", None,
            "ZS", None, None, None, None, None,
        ],
        "emitido_em": "2026-10-14T12:00:00Z",
        "registrado_em": "2026-10-14T12:01:00Z",
        "treinado_ate": "2026-10-13T10:00:00Z",
        "sessao_base": "2026-10-13", "sessao_alvo": "2026-10-15",
        "horizonte_sessoes": 2, "preco_base": "1000",
        "base_edicao_sha256": SHA_A,
        "regra_rotulagem": "retorno-banda-1pct",
        "banda_relativa": "0.01",
        "probabilidades": {
            "ALTA": "0.7", "BAIXA": "0.2", "ESTABILIDADE": "0.1",
        },
        "evidencia_registro_id": "CAPTURA-TESTE-001",
        "evidencia_registro_sha256": SHA_E,
    }


def calendario():
    return {
        "mercado": "CME", "fonte_id": "CALENDARIO_SINTETICO",
        "edicao_sha256": SHA_E,
        "publicacao_em": "2026-10-12T10:00:00Z",
        "coleta_em": "2026-10-12T11:00:00Z",
        "sessoes": ["2026-10-13", "2026-10-14", "2026-10-15"],
    }


def executar(p=None, base=None, alvo=None, cal=None, corte=CORTE):
    r = criar_registro_previsao(p or previsao())
    return reconciliar_previsao(
        r, cadeia=[r], cabeca_esperada_sha256=r["registro_sha256"],
        precos_base=base if base is not None else [cotacao("2026-10-13", "1000", SHA_A)],
        precos_alvo=alvo if alvo is not None else [cotacao("2026-10-15", "1020", SHA_C)],
        calendario_sessoes=cal or calendario(), as_of=corte,
    )


class TestProvenienciaPrevisoes(unittest.TestCase):
    def test_sha_deterministico_e_cadeia_sintetica(self):
        p = previsao()
        a = criar_registro_previsao(p)
        b = criar_registro_previsao(p)
        self.assertEqual(a["registro_sha256"], b["registro_sha256"])
        self.assertEqual(a["anterior_sha256"], GENESIS)
        prova = verificar_cadeia_previsoes([a],
                                           cabeca_esperada_sha256=a["registro_sha256"])
        self.assertEqual(prova["quantidade"], 1)
        self.assertFalse(prova["ancora_externa_autenticada"])

    def test_cadeia_de_dois_registros(self):
        a = criar_registro_previsao(previsao())
        p = previsao()
        p["previsao_id"] = "TESTE-002"
        p["evidencia_registro_id"] = "CAPTURA-TESTE-002"
        p["registrado_em"] = "2026-10-14T12:02:00Z"
        b = criar_registro_previsao(p, anterior_sha256=a["registro_sha256"])
        self.assertEqual(verificar_cadeia_previsoes(
            [a, b], cabeca_esperada_sha256=b["registro_sha256"]
        )["quantidade"], 2)
        with self.assertRaisesRegex(ErroRegistroPrevisao, "âncora"):
            verificar_cadeia_previsoes(
                [a], cabeca_esperada_sha256=b["registro_sha256"])

    def test_probabilidade_alterada_sem_atualizar_sha(self):
        a = criar_registro_previsao(previsao())
        falsificado = copy.deepcopy(a)
        falsificado["previsao"]["probabilidades"]["ALTA"] = "0.6"
        falsificado["previsao"]["probabilidades"]["BAIXA"] = "0.3"
        with self.assertRaisesRegex(ErroRegistroPrevisao, "adulterado"):
            verificar_cadeia_previsoes(
                [falsificado], cabeca_esperada_sha256=a["registro_sha256"])

    def test_reescrita_da_cadeia_requer_ancora_falsa(self):
        a = criar_registro_previsao(previsao())
        p = previsao()
        p["preco_base"] = "2000"
        b = criar_registro_previsao(p)
        with self.assertRaisesRegex(ErroRegistroPrevisao, "âncora"):
            verificar_cadeia_previsoes(
                [b], cabeca_esperada_sha256=a["registro_sha256"])

    def test_registro_intempestivo_bloqueia(self):
        p = previsao()
        p["registrado_em"] = "2026-10-15T12:00:00Z"
        with self.assertRaisesRegex(ErroRegistroPrevisao, "extemporaneamente"):
            criar_registro_previsao(p)

    def test_extra_campos_e_probabilidades_invalidas(self):
        for change in (
            {"falso": "campo"},
            {"probabilidades": {"ALTA": "0.9", "BAIXA": "0.2",
                               "ESTABILIDADE": "0.1"}},
            {"treinado_ate": "2026-10-16T12:00:00Z"},
            {"preco_base": "NaN"},
            {"base_edicao_sha256": "INVALIDO"},
            {"emitido_em": "2026-10-14T12:00:00"},
        ):
            with self.subTest(change=change), self.assertRaises(ErroRegistroPrevisao):
                criar_registro_previsao(dict(previsao(), **change))

    def test_reconciliacao_retorna_backtest_realizado_sem_skill(self):
        res = executar()
        self.assertEqual(res["status"], "RECONCILIADO_OFFLINE_NAO_HOMOLOGADO")
        self.assertEqual(res["item_backtest"]["classe_realizada"], "ALTA")
        self.assertEqual(res["item_backtest"]["valor_base"], "1000")
        self.assertEqual(res["item_backtest"]["valor_alvo"], "1020")
        self.assertEqual(res["item_backtest"]["horizonte_sessoes"], 2)
        self.assertEqual(res["item_backtest"]["edicao_real_sha256"], SHA_C)
        self.assertFalse(res["publicavel"])
        self.assertIsNone(res["probabilidades_calibradas"])
        self.assertFalse(res["previsao_historica_independente_comprovada"])

    def test_revisao_base_posterior_emissao_nao_contamina(self):
        revisao = cotacao("2026-10-13", "1300", SHA_B)
        revisao.update({
            "publicacao_em": "2026-10-14T15:00:00Z",
            "coleta_em": "2026-10-14T16:00:00Z",
            "revisao_de_sha256": SHA_A,
        })
        res = executar(base=[cotacao("2026-10-13", "1000", SHA_A),
                             revisao])
        self.assertEqual(res["item_backtest"]["valor_base"], "1000")
        self.assertEqual(res["preco_base_edicao_sha256"], SHA_A)

    def test_base_retroativa_ou_preco_reescrito_bloqueia(self):
        p = previsao()
        p["preco_base"] = "1300"
        with self.assertRaisesRegex(ErroRegistroPrevisao, "preço-base"):
            executar(p=p)
        p = previsao()
        p["base_edicao_sha256"] = SHA_B
        with self.assertRaisesRegex(ErroRegistroPrevisao, "preço-base"):
            executar(p=p)

    def test_revisao_alvo_asof_da_avaliacao(self):
        rev = cotacao("2026-10-15", "990", SHA_B)
        rev.update({
            "publicacao_em": "2026-10-16T08:00:00Z",
            "coleta_em": "2026-10-16T09:00:00Z",
            "revisao_de_sha256": SHA_C,
        })
        res = executar(alvo=[cotacao("2026-10-15", "1020", SHA_C), rev])
        self.assertEqual(res["item_backtest"]["classe_realizada"], "ESTABILIDADE")
        self.assertEqual(res["item_backtest"]["valor_alvo"], "990")

    def test_revisao_alvo_apos_corte_nao_contamina(self):
        rev = cotacao("2026-10-15", "990", SHA_B)
        rev.update({
            "publicacao_em": "2026-10-17T08:00:00Z",
            "coleta_em": "2026-10-17T09:00:00Z",
            "revisao_de_sha256": SHA_C,
        })
        res = executar(alvo=[cotacao("2026-10-15", "1020", SHA_C), rev])
        self.assertEqual(res["item_backtest"]["valor_alvo"], "1020")

    def test_horizonte_falso_bloqueia(self):
        p = previsao()
        p["horizonte_sessoes"] = 1
        with self.assertRaisesRegex(ErroRegistroPrevisao, "horizonte"):
            executar(p=p)

    def test_mercado_identidade_divergente_bloqueia(self):
        p = previsao()
        p["identidade_economica"][6] = "OUTRO"
        with self.assertRaisesRegex(ErroRegistroPrevisao, "instrumento"):
            executar(p=p)

    def test_sem_price_base_disponivel_na_emissao(self):
        tardio = cotacao("2026-10-13", "1000", SHA_A)
        tardio.update({
            "publicacao_em": "2026-10-14T13:00:00Z",
            "coleta_em": "2026-10-14T14:00:00Z",
        })
        with self.assertRaisesRegex(ErroRegistroPrevisao, "visível"):
            executar(base=[tardio])

    def test_previsao_fora_da_cadeia_nao_basta_com_mesmo_digest(self):
        a = criar_registro_previsao(previsao())
        clone = copy.deepcopy(a)
        clone["publicavel"] = True
        with self.assertRaisesRegex(ErroRegistroPrevisao, "integralmente"):
            reconciliar_previsao(
                clone, cadeia=[a], cabeca_esperada_sha256=a["registro_sha256"],
                precos_base=[cotacao("2026-10-13", "1000", SHA_A)],
                precos_alvo=[cotacao("2026-10-15", "1020", SHA_C)],
                calendario_sessoes=calendario(), as_of=CORTE)

    def test_cadeia_com_identidade_duplicada(self):
        p = previsao()
        a = criar_registro_previsao(p)
        b = criar_registro_previsao(p, anterior_sha256=a["registro_sha256"])
        with self.assertRaisesRegex(ErroRegistroPrevisao, "duplicado"):
            verificar_cadeia_previsoes(
                [a,b], cabeca_esperada_sha256=b["registro_sha256"])


if __name__ == "__main__":
    unittest.main()
