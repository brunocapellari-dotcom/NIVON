"""Regressões do encadeamento: preços com vintages + calendário + força."""
import unittest

from nivon.qualidade_mercados import (
    ErroQualidadeMercado, dinamica_preco_auditada,
)

DAYS = [
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06",
    "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12",
    "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16",
]
AS_OF = "2026-10-20T12:00:00Z"
SHA_A = "a" * 64
SHA_B = "b" * 64
CAL_SHA = "d" * 64


def cotacao(i, valor, *, fisico=False, **overrides):
    dia = DAYS[i]
    r = {
        "mercado": "CME", "produto": "SOJA", "contrato": "2026-11",
        "tipo": "AJUSTE", "unidade": "USC/BU", "instrumento_id": "ZS",
        "data_referencia": dia, "competencia": dia[:7],
        "referencia_em": dia+"T16:00:00-04:00",
        "publicacao_em": dia+"T16:30:00-04:00",
        "coleta_em": dia+"T17:00:00-04:00",
        "fonte_id": "COTACAO_FIXTURE", "fonte_url": "https://example.org/teste",
        "edicao_sha256": SHA_A, "preco": str(valor),
    }
    if fisico:
        r.update({
            "mercado": "FISICO", "contrato": None, "instrumento_id": None,
            "localidade_ibge": "5107602", "tipo": "INDICADOR_FISICO",
            "unidade": "BRL/SC60KG", "ponto_cotacao_id": "ARMAZEM_A",
            "qualidade_id": "SOJA_PADRAO", "condicao_entrega_id": "FOB",
            "condicao_pagamento_id": "D7", "regime_tributario_id": "ICMS_MT",
        })
    r.update(overrides)
    return r


def precos(valores, *, fisico=False):
    return [cotacao(i,v,fisico=fisico) for i,v in enumerate(valores)]


def calendario(*, fisico=False, sessoes=None):
    return {
        "mercado": "FISICO" if fisico else "CME",
        "fonte_id": "CALENDARIO_FIXTURE",
        "edicao_sha256": CAL_SHA,
        "publicacao_em": "2026-09-29T10:00:00Z",
        "coleta_em": "2026-09-29T11:00:00Z",
        "sessoes": list(DAYS) if sessoes is None else sessoes,
    }


def avaliar(rows, *, fisico=False, **params):
    opt = {
        "as_of": AS_OF, "janela": 6, "tolerancia_absoluta": 1,
        "calendario_sessoes": calendario(fisico=fisico),
    }
    opt.update(params)
    return dinamica_preco_auditada(rows,**opt)


class TestDinamicaPrecoAuditada(unittest.TestCase):
    def test_cbot_alta_fortalecendo_historicamente(self):
        r = avaliar(precos([1000,1001,1002,1003,1004,1005,
                            1006,1009,1012,1015,1018,1021]))
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertEqual(r["dinamica"], "AUMENTO_DE_FORCA")
        self.assertEqual(r["identidade_economica"][:5],
                         ["CME","SOJA","2026-11","AJUSTE","USC/BU"])
        self.assertEqual(r["cobertura_calendario"]["sessoes_conferidas"],12)
        self.assertFalse(r["precos_homologados"])
        self.assertFalse(r["direitos_publicacao_verificados"])
        self.assertIsNone(r["probabilidades_calibradas"])
        self.assertFalse(r["publicavel"])

    def test_cbot_reversao_observada(self):
        r = avaliar(precos([1000,1002,1004,1006,1008,1010,
                            1010,1008,1006,1004,1002,1000]))
        self.assertEqual(r["dinamica"],"REVERSAO_OBSERVADA")
        self.assertEqual(r["tendencia_anterior"],"ALTA")
        self.assertEqual(r["tendencia_atual"],"BAIXA")

    def test_fisico_mesma_praca_e_condicoes(self):
        r=avaliar(precos([100,101,102,103,104,105,
                          106,108,110,112,114,116],fisico=True),fisico=True)
        self.assertEqual(r["identidade_economica"][0],"FISICO")
        self.assertEqual(r["identidade_economica"][5],"5107602")
        self.assertEqual(r["dinamica"],"AUMENTO_DE_FORCA")

    def test_fisico_condicao_pagamento_diferente_bloqueia(self):
        rows=precos([100]*12,fisico=True)
        rows[6]["condicao_pagamento_id"]="D0"
        with self.assertRaisesRegex(ErroQualidadeMercado,"mistura"):
            avaliar(rows,fisico=True)

    def test_fisico_outro_armazem_bloqueia(self):
        rows=precos([100]*12,fisico=True)
        rows[6]["ponto_cotacao_id"]="ARMAZEM_B"
        with self.assertRaisesRegex(ErroQualidadeMercado,"mistura"):
            avaliar(rows,fisico=True)

    def test_cbot_outro_vencimento_bloqueia(self):
        rows=precos([1000]*12)
        rows[6]["contrato"]="2027-01"
        with self.assertRaisesRegex(ErroQualidadeMercado,"mistura"):
            avaliar(rows)

    def test_cbot_tipo_ajuste_vs_fechamento_bloqueia(self):
        rows=precos([1000]*12)
        rows[6]["tipo"]="FECHAMENTO"
        with self.assertRaisesRegex(ErroQualidadeMercado,"mistura"):
            avaliar(rows)

    def test_lacuna_em_calendario_bloqueia(self):
        sessoes=DAYS[:7]+["2026-10-10"]+DAYS[7:]
        with self.assertRaisesRegex(ValueError,"lacuna"):
            avaliar(precos([1000]*12),calendario_sessoes=calendario(sessoes=sessoes))

    def test_sem_calendario_indeterminado(self):
        r=avaliar(precos([1000]*12),calendario_sessoes=None)
        self.assertEqual(r["status"],"CALENDARIO_AUSENTE")
        self.assertEqual(r["dinamica"],"INDETERMINADA")
        self.assertFalse(r["publicavel"])

    def test_11_sessoes_nao_viram_12(self):
        r=avaliar(precos([1000]*11),
                  calendario_sessoes=calendario(sessoes=DAYS[:11]))
        self.assertEqual(r["status"],"DADOS_INSUFICIENTES")
        self.assertEqual(r["tendencia"],"INDETERMINADA")
        self.assertEqual(r["cobertura_calendario"]["sessoes_conferidas"],11)

    def test_coleta_futura_bloqueia(self):
        rows=precos([1000]*12)
        rows[5]["coleta_em"]="2026-10-21T12:00:00Z"
        with self.assertRaisesRegex(ErroQualidadeMercado,"point-in-time"):
            avaliar(rows)

    def test_revisao_invalida_bloqueia(self):
        rows=precos([1000]*12)
        rows.append({**rows[3],"preco":"1100","edicao_sha256":SHA_B})
        with self.assertRaisesRegex(ErroQualidadeMercado,"revisão"):
            avaliar(rows)

    def test_revisao_valida_e_proveniencia(self):
        rows=precos([1000]*12)
        rows.append({
            **rows[3], "preco":"1001", "edicao_sha256":SHA_B,
            "revisao_de_sha256":SHA_A,
            "publicacao_em":DAYS[3]+"T17:30:00-04:00",
            "coleta_em":DAYS[3]+"T18:00:00-04:00",
        })
        r=avaliar(rows)
        self.assertEqual(r["revisoes_resolvidas"],1)
        self.assertFalse(r["publicavel"])

    def test_calendario_outro_mercado_bloqueia(self):
        with self.assertRaises(ValueError):
            avaliar(precos([1000]*12),calendario_sessoes=calendario(fisico=True))

    def test_fonte_mista_bloqueia(self):
        rows=precos([1000]*12)
        rows[4]["fonte_id"]="NAO_MISTURAR"
        with self.assertRaisesRegex(ErroQualidadeMercado,"mistura"):
            avaliar(rows)

    def test_ruido_historico_nao_vira_reversao(self):
        r=avaliar(precos([1000,1020,980,1019,981,1002,
                          1004,1006,1008,1010,1012,1014]))
        self.assertEqual(r["dinamica"],"INDETERMINADA")

    def test_sem_banda_nao_classifica(self):
        with self.assertRaisesRegex(ValueError,"limiar"):
            avaliar(precos([1000]*12),tolerancia_absoluta=0)

    def test_janela_invalida_bloqueia(self):
        for v in (0,3,True,49):
            with self.subTest(v=v),self.assertRaises(ErroQualidadeMercado):
                avaliar(precos([1000]*12),janela=v)


if __name__ == "__main__":
    unittest.main()
