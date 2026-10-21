"""Somente fixtures sintéticas: cobertura de horizonte NÃO é backtest OOS."""
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from nivon.fretes_cobertura_horizontes import (
    ErroCoberturaFrete, auditar_cobertura_horizontes_frete,
)
from nivon.fretes_painel_pr30 import ErroPainelFrete
from nivon.fretes_registros import OfertaFrete

INICIO = date(2026, 4, 1)
CORTE = datetime(2026, 9, 1, 16, tzinfo=timezone.utc)


def dado(j, i=1):
    dia = INICIO + timedelta(days=j)
    pub = datetime(dia.year, dia.month, dia.day, 15, tzinfo=timezone.utc)
    valor = Decimal(200+j+i)
    return OfertaFrete(
        publicacao_id=f"pub:{j}:{i}",
        registro_id=f"reg:{j}:{i}",
        oferta_id=f"offer:{j}:{i}",
        municipio_ibge="5107925", destino_ibge="5107602",
        pickup_entity_id=f"ponto:{i}",
        transportadora_id=f"transportadora:{i}",
        descarga_entity_id="terminal:teste",
        produto="MILHO", equipamento="RODOTREM", regime="PJ",
        frete_base_brl_t=valor, pedagio_brl_t=Decimal(10),
        frete_cheio_brl_t=valor+10, data_referencia=dia,
        data_publicacao=pub, data_coleta=pub+timedelta(minutes=15),
        fonte_id="FONTE-FIXTURE",
    )


def historico(dias=125):
    return [dado(j, i) for j in range(dias) for i in (1, 2)]


def avaliar(registros, **kw):
    params = {
        "origem_ibge": "5107925", "destino_ibge": "5107602",
        "descarga_entity_id": "terminal:teste",
        "produto": "MILHO", "equipamento": "RODOTREM",
        "regime": "PJ", "pedagio": "ADICIONAL",
        "as_of": CORTE,
    }
    params.update(kw)
    return auditar_cobertura_horizontes_frete(registros, **params)


class TestCoberturaHorizontesFrete(unittest.TestCase):
    def test_7_30_90_dias_corridos_uteis_ao_preflight(self):
        r = avaliar(historico())
        self.assertEqual(r["dias_observados"], 125)
        self.assertEqual([x["horizonte_dias_corridos"] for x in r["horizontes"]],
                         [7, 30, 90])
        self.assertEqual([x["origens_com_pares_comparaveis"] for x in r["horizontes"]],
                         [118, 95, 35])
        self.assertTrue(all(x["status"] ==
            "ALVOS_HISTORICOS_IDENTIFICADOS_SEM_FORECAST_ARQUIVADO"
            for x in r["horizontes"]))
        self.assertTrue(all(x["avaliacao_oos_executada"] is False for x in r["horizontes"]))
        self.assertFalse(r["backtest_executado"])
        self.assertFalse(r["historico_real_homologado"])
        self.assertFalse(r["publicavel"])
        self.assertIsNone(r["probabilidades_calibradas"])

    def test_60_dias_nao_sao_suficientes_para_90(self):
        r=avaliar(historico(60))
        self.assertEqual([x["origens_com_pares_comparaveis"] for x in r["horizontes"]],
                         [53,30,0])
        self.assertEqual(r["horizontes"][2]["status"],"COBERTURA_INSUFICIENTE")

    def test_falta_de_dia_nao_se_preenche(self):
        origem=historico()
        removidos=[x for x in origem
                    if x.data_referencia != INICIO+timedelta(days=90)]
        r=avaliar(removidos)
        self.assertEqual(r["dias_observados"],124)
        self.assertEqual(r["horizontes"][0]["origens_com_pares_comparaveis"],116)
        self.assertEqual(r["horizontes"][1]["origens_com_pares_comparaveis"],93)
        self.assertEqual(r["horizontes"][2]["origens_com_pares_comparaveis"],34)

    def test_mudanca_de_composicao_entre_datas_bloqueia_90_dias(self):
        rows=historico()
        rows=[
            replace(x, pickup_entity_id=f"novo:{x.pickup_entity_id}",
                    transportadora_id=f"novo:{x.transportadora_id}")
            if (x.data_referencia-INICIO).days >= 65 else x
            for x in rows
        ]
        r=avaliar(rows)
        self.assertEqual(r["horizontes"][2]["origens_com_pares_comparaveis"],0)
        self.assertEqual(r["horizontes"][2]["status"],"COBERTURA_INSUFICIENTE")
        self.assertGreater(r["horizontes"][0]["origens_com_pares_comparaveis"],0)

    def test_um_par_nao_e_painel_comparavel(self):
        rows=[x for x in historico() if x.pickup_entity_id=="ponto:1"]
        r=avaliar(rows)
        self.assertTrue(all(x["origens_com_pares_comparaveis"]==0 for x in r["horizontes"]))
        self.assertTrue(all(x["origens_com_pares_insuficientes"]>0 for x in r["horizontes"]))

    def test_reposts_nao_criam_novas_amostras(self):
        rows=historico()
        for k in range(15):
            rows.append(replace(rows[0],publicacao_id=f"rep:{k}",
                                registro_id=f"rep-reg:{k}",
                                oferta_id=f"rep-offer:{k}"))
        r=avaliar(rows)
        self.assertEqual(r["quantidade_bruta"],265)
        self.assertEqual(r["repeticoes_deduplicadas"],15)
        self.assertEqual(r["horizontes"][0]["origens_com_pares_comparaveis"],118)
        self.assertEqual(r["horizontes"][0]["pares_origem_alvo_total_nao_independentes"],236)

    def test_conflito_mesmo_par_mesmo_dia_rejeitado(self):
        rows=historico(20)
        rows.append(replace(rows[0],publicacao_id="fraude",registro_id="fraude",
            oferta_id="fraude",frete_base_brl_t=Decimal(900),
            frete_cheio_brl_t=Decimal(910)))
        with self.assertRaisesRegex(ErroPainelFrete,"conflitantes"):
            avaliar(rows)

    def test_coleta_apos_asof_rejeitada(self):
        rows=historico(20)
        with self.assertRaisesRegex(ErroPainelFrete,"futura"):
            avaliar(rows,as_of=datetime(2026,4,10,16,tzinfo=timezone.utc))

    def test_categoria_produto_misturada_rejeita(self):
        rows=historico(20)
        rows[0]=replace(rows[0],produto="SOJA")
        with self.assertRaisesRegex(ErroPainelFrete,"mistura"):
            avaliar(rows)

    def test_datas_futuras_nao_constituem_rotulo_conhecido(self):
        rows=historico(30)
        r=avaliar(rows)
        self.assertGreater(r["horizontes"][2]["origens_ainda_nao_maturadas"],0)
        self.assertEqual(r["horizontes"][2]["origens_com_pares_comparaveis"],0)

    def test_horizonte_requer_dias_corridos_exatos(self):
        rows=historico(20)
        r=avaliar(rows,horizontes_dias=(7,),minimo_origens_por_horizonte=5)
        self.assertEqual(r["horizontes"][0]["origens_com_pares_comparaveis"],13)
        self.assertEqual(r["horizontes"][0]["amostras_de_evidencia"][0]["data_alvo"],
                         (INICIO+timedelta(days=7)).isoformat())

    def test_horizontes_duplicados_ou_booleanos_bloqueados(self):
        for hs in ((7,7),(90,30),(True,30),(0,7),(366,),(),[7,30]):
            with self.subTest(hs=hs),self.assertRaises(ErroCoberturaFrete):
                avaliar(historico(5),horizontes_dias=hs)

    def test_minimos_invalidos(self):
        for opts in ({"minimo_pares_por_origem":1},
                     {"minimo_origens_por_horizonte":0},
                     {"minimo_pares_por_origem":True},
                     {"minimo_origens_por_horizonte":True}):
            with self.subTest(opts=opts),self.assertRaises(ErroCoberturaFrete):
                avaliar(historico(5),**opts)

    def test_asof_ingenuo_rejeitado(self):
        with self.assertRaisesRegex(ErroCoberturaFrete,"timezone-aware"):
            avaliar(historico(5),as_of=datetime(2026,9,1,16))

    def test_compromisso_deterministico(self):
        a=avaliar(historico(30),horizontes_dias=(7,))
        b=avaliar(list(reversed(historico(30))),horizontes_dias=(7,))
        self.assertEqual(a["horizontes"][0]["fingerprint_cobertura_sha256"],
                         b["horizontes"][0]["fingerprint_cobertura_sha256"])

    def test_nao_confunde_pares_com_caminhoes_ou_fretes_contratados(self):
        r=avaliar(historico(60))
        t=str(r)
        for banned in ("volume_transportado", "frete_contratado", "probabilidades_calibradas': {"):
            self.assertNotIn(banned,t)
        self.assertFalse(r["previsoes_arquivadas_validadas"])
        self.assertFalse(r["integridade_raw_comprovada"])
        self.assertFalse(r["licenca_de_uso_e_redistribuicao_comprovada"])


if __name__=="__main__":
    unittest.main()
