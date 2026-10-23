"""Reconciliação PR #30 e PR #18/Quant: um único R01 estatístico.

A mesma entrada de painel retorna as mesmas estatísticas do núcleo
fretes_tendencia_pareada, não as medianas de níveis do modo legado.
Fixtures sintéticas; nenhum dado publicado, real ou contratado.
"""
import unittest
from unittest.mock import patch

from nivon.motor_tendencias import ErroTendencia
from nivon.fretes_tendencia_pareada import tendencia_frete_pareado
from nivon.tendencias_mercados import tendencia_frete_anunciado
from nivon.pipeline_fretes_quant import executar_lote_fretes_quant

SESSOES = ("2026-10-07","2026-10-08","2026-10-09",
           "2026-10-13","2026-10-14","2026-10-15")
ORIGEM = "5104526"
DESTINO = "5107602"
DESCARGA = "terminal:001"


def painel(*, estabilidade=False, rotacao=False):
    rows=[]
    for t,dia in enumerate(SESSOES):
        for i in range(3):
            identidade = f"ponto:{i}" if not(rotacao and i == 2) else (
                "ponto:antigo" if t < 3 else "ponto:novo")
            preco = 140+7*i+(0 if estabilidade else 3*t)
            rows.append({
                "periodo":dia,"publicacao":dia,"coleta":dia,
                "valor":preco,"fonte_id":"FONTE_OFFLINE",
                "edicao_sha256":"a"*64,"origem_ibge":ORIGEM,
                "destino_ibge":DESTINO,"produto":"MILHO",
                "veiculo":"RODOTREM","pedagio":"ADICIONAL",
                "descarga_entity_id":DESCARGA,"regime":"PJ",
                "natureza":"OFERTA","unidade":"BRL/T",
                "lote_id":f"lote:{t}:{i}",
                "pickup_entity_id":identidade,
                "transportadora_id":f"transportadora:{i}",
                "preco_rs_t":str(preco),
            })
    return rows


def args():
    return {
        "origem_ibge":ORIGEM, "destino_ibge":DESTINO,
        "produto":"MILHO","veiculo":"RODOTREM",
        "pedagio":"ADICIONAL","descarga_entity_id":DESCARGA,
        "regime":"PJ","as_of":"2026-10-20",
        "janela":6,"minimo_lotes_dia":2,
        "tolerancia_absoluta":2,
    }


class TestReconciliacaoR01(unittest.TestCase):
    def test_api_pr30_direciona_painel_ao_motor_unico(self):
        for dados in (painel(), painel(estabilidade=True),
                      painel(rotacao=True)):
            with self.subTest(caso=dados[0]["preco_rs_t"]):
                out = tendencia_frete_anunciado(dados, **args())
                esperado = tendencia_frete_pareado(dados, **args())
                for key in ("status","tendencia","orientacao","publicavel"):
                    self.assertEqual(out[key],esperado[key])
                if "cobertura_amostral" in esperado:
                    self.assertEqual(out["cobertura_amostral"],
                                     esperado["cobertura_amostral"])
                self.assertEqual(out["motor_r01_canonico"],
                                 "PAINEL_PAREADO_ESTABELECIMENTO_TRANSPORTADORA")
                self.assertFalse(out["publicavel"])
                self.assertNotIn("media_municipal",str(out))
                self.assertNotIn("preco_mediano_rs_t_mesmo_estabelecimento",str(out))

    def test_invariancia_entrada_repost_nao_inflaciona_pares(self):
        raw=painel()
        base=tendencia_frete_anunciado(raw,**args())
        extra=tendencia_frete_anunciado(raw+[dict(raw[0]) for _ in range(25)],**args())
        self.assertEqual(extra["tendencia"],base["tendencia"])
        self.assertEqual(extra["identidades_comparaveis"],base["identidades_comparaveis"])
        self.assertEqual(extra["reenvios_deduplicados"],25)

    def test_sem_parcial_de_ponto_transportadora(self):
        with self.assertRaisesRegex(ErroTendencia,"ambos"):
            tendencia_frete_anunciado(painel(),**args(),pickup_entity_id="ponto:1")
        with self.assertRaisesRegex(ErroTendencia,"ambos"):
            tendencia_frete_anunciado(painel(),**args(),
                                     transportadora_id="transportadora:1")

    def test_pr30_rejeita_mudanca_regime_descarga_e_condicoes(self):
        for field,value in (
            ("regime","PF"),("descarga_entity_id","terminal:002"),
            ("pedagio","INCLUSO"),("veiculo","BITREM"),
            ("produto","SOJA"),("destino_ibge","5100000"),
            ("natureza","CONTRATADO")
        ):
            raw=painel()
            raw[0][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(
                ErroTendencia,"mistura"
            ):
                tendencia_frete_anunciado(raw,**args())

    def test_modo_legado_exige_um_par_e_nao_muda_o_resultado_anterior(self):
        raw=painel()
        # O modo de lotes por único par continua isolado; com só um lote
        # em cada dia ele não inventa um painel multi-par.
        rows=[x for x in raw if x["pickup_entity_id"]=="ponto:1"]
        out=tendencia_frete_anunciado(
            rows,**args(),
            pickup_entity_id="ponto:1",
            transportadora_id="transportadora:1"
        )
        self.assertEqual(out["status"],"AMOSTRA_INSUFICIENTE")
        self.assertEqual(out["motor_r01_canonico"],"LEGADO_LOTES_INTRAPAR_ISOLADO")
        self.assertFalse(out["publicavel"])

    def test_contrato_r01_painel_chama_funcao_unica_na_pipeline(self):
        from test_pipeline_fretes_quant import anunciados, ASOF
        with patch("nivon.fretes_integracao_r01.tendencia_frete_anunciado",
                   wraps=tendencia_frete_anunciado) as spy:
            out=executar_lote_fretes_quant(anunciados(),as_of=ASOF)
        self.assertEqual(spy.call_count,1)
        self.assertEqual(out["n_paineis_comerciais"],1)
        self.assertEqual(
            out["tendencias_pareadas"][0]["resultado"]["motor_r01_canonico"],
            "PAINEL_PAREADO_ESTABELECIMENTO_TRANSPORTADORA"
        )
        self.assertEqual(
            out["tendencias_pareadas"][0]["resultado"]["motor"],
            "R01_PR30_PAREADO_UNIFICADO"
        )
        self.assertFalse(out["publicavel"])


if __name__=="__main__":
    unittest.main()
