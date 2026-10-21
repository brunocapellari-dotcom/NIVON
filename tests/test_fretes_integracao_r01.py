"""Regressões cruzadas para PR #18 + metodologia da PR #30."""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from nivon.fretes_integracao_r01 import tendencia_ofertas_pareadas
from nivon.fretes_painel_pr30 import ErroPainelFrete
from nivon.fretes_registros import OfertaFrete


def dado(dia: date, i: int, preco: int, **changes) -> OfertaFrete:
    ts = datetime(dia.year, dia.month, dia.day, 15, tzinfo=timezone.utc)
    base = dict(
        publicacao_id=f"pub:{dia}:{i}",
        registro_id=f"reg:{dia}:{i}",
        oferta_id=f"offer:{dia}:{i}",
        municipio_ibge="5107925", destino_ibge="5107602",
        pickup_entity_id=f"ponto:{i}", transportadora_id=f"carrier:{i}",
        descarga_entity_id="terminal:1", produto="SOJA",
        equipamento="RODOTREM", regime="PJ",
        frete_base_brl_t=Decimal(preco), pedagio_brl_t=Decimal("10"),
        frete_cheio_brl_t=Decimal(preco + 10),
        data_referencia=dia, data_publicacao=ts,
        data_coleta=ts + timedelta(minutes=15),
        fonte_id="SINTETICO",
    )
    base.update(changes)
    return OfertaFrete(**base)


def seis_dias(inclinacao=3):
    primeiro = date(2026, 10, 12)
    return [
        dado(primeiro+timedelta(days=j), i,
             150+i*20+j*inclinacao)
        for j in range(6) for i in (1,2)
    ]


def analisar(rows, **overrides):
    args = dict(
        origem_ibge="5107925", destino_ibge="5107602",
        descarga_entity_id="terminal:1", produto="SOJA",
        equipamento="RODOTREM", regime="PJ", pedagio="ADICIONAL",
        as_of=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
        janela=6, minimo_pares=2, tolerancia_absoluta=2,
    )
    args.update(overrides)
    return tendencia_ofertas_pareadas(rows, **args)


class TestIntegracaoR01(unittest.TestCase):
    def test_sinal_de_alta_apenas_por_pares_constantes(self):
        r = analisar(seis_dias())
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertEqual(r["metrica_tendencia"],
                         "VARIACAO_PAREADA_POR_ESTABELECIMENTO_TRANSPORTADORA")
        self.assertEqual(r["tipo_de_valor"],
                         "VARIACAO_PRECO_BASE_ANUNCIADO_NAO_PRECO_MUNICIPAL")
        self.assertEqual(len(r["identidades_comparaveis"]), 2)
        self.assertEqual(r["descarga_entity_id"], "terminal:1")
        self.assertEqual(r["regime"], "PJ")
        self.assertEqual(r["quantidade_bruta"], 12)
        self.assertFalse(r["publicavel"])
        self.assertIsNone(r["probabilidades_calibradas"])
        self.assertNotIn("preco_medio_municipio", str(r))
        self.assertNotIn("volume_realizado", str(r))

    def test_baixa_e_estabilidade_ressalvadas_nao_sao_previsao(self):
        self.assertEqual(analisar(seis_dias(-3))["tendencia"], "BAIXA")
        self.assertEqual(analisar(seis_dias(0))["tendencia"], "ESTABILIDADE")

    def test_composicao_variavel_nao_gera_alta_falsa(self):
        rows = seis_dias(0)
        primeiro = date(2026, 10, 12)
        for j in range(6):
            dia=primeiro+timedelta(days=j)
            rows.append(dado(
                dia, 3, 100 if j < 3 else 1000,
                pickup_entity_id="rotativo:A" if j < 3 else "rotativo:B"
            ))
        r=analisar(rows)
        self.assertEqual(r["tendencia"], "ESTABILIDADE")
        self.assertEqual(len(r["identidades_comparaveis"]), 2)
        self.assertEqual(r["identidades_dia"], 18)
        self.assertFalse(r["publicavel"])

    def test_sem_painel_pareado_abre_bloqueio(self):
        rows=seis_dias()
        rows=[
            replace(x, pickup_entity_id=f"novo:{x.data_referencia}"
                    if x.pickup_entity_id=="ponto:2" else x.pickup_entity_id)
            for x in rows
        ]
        r=analisar(rows)
        self.assertEqual(r["status"], "PAINEL_INCOMPARAVEL")
        self.assertEqual(r["tendencia"], "INDETERMINADA")

    def test_mesmo_dia_preco_diferente_nao_e_media(self):
        rows=seis_dias()
        conflitante=replace(
            rows[0], publicacao_id="pub:outro", registro_id="reg:outro",
            oferta_id="offer:outro", frete_base_brl_t=Decimal(400),
            frete_cheio_brl_t=Decimal(410),
        )
        with self.assertRaisesRegex(ErroPainelFrete,"conflitantes"):
            analisar(rows+[conflitante])

    def test_mesmo_dia_pedagio_diferente_nao_e_deduplicado(self):
        rows=seis_dias()
        conflitante=replace(
            rows[0], publicacao_id="pub:outro", registro_id="reg:outro",
            oferta_id="offer:outro", pedagio_brl_t=Decimal(15),
            frete_cheio_brl_t=rows[0].frete_base_brl_t+Decimal(15),
        )
        with self.assertRaisesRegex(ErroPainelFrete,"pedágios conflitantes"):
            analisar(rows+[conflitante])

    def test_defasagem_temporal_de_oferta_velha_bloqueada(self):
        rows=seis_dias()
        nova=replace(rows[0], data_referencia=date(2024,1,1))
        with self.assertRaisesRegex(ErroPainelFrete,"referência defasada"):
            analisar([nova]+rows[1:])

    def test_corte_intradiario_futuro_impede_vazamento(self):
        rows=seis_dias()
        with self.assertRaisesRegex(ErroPainelFrete,"futura"):
            analisar(rows, as_of=datetime(2026, 10, 17, 14, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ErroPainelFrete,"futura"):
            analisar(rows, as_of=datetime(2026, 10, 17, 15, 5, tzinfo=timezone.utc))

    def test_pareamento_recusa_pf_pj_descarga_produto_e_equipamento_misturados(self):
        for field, value in [
            ("regime","PF"),
            ("descarga_entity_id","terminal:2"),
            ("produto","MILHO"),
            ("equipamento","BITREM"),
            ("destino_ibge","1503606"),
        ]:
            rows=seis_dias()
            rows[0]=replace(rows[0], **{field:value})
            with self.subTest(field=field), self.assertRaisesRegex(ErroPainelFrete,"mistura"):
                analisar(rows)

    def test_varias_publicacoes_mesmo_preco_nao_aumentam_pares(self):
        rows=seis_dias()
        for idx in range(4):
            rows.append(replace(
                rows[0], publicacao_id=f"pub:rep{idx}",
                registro_id=f"reg:rep{idx}", oferta_id=f"offer:rep{idx}",
            ))
        r=analisar(rows)
        self.assertEqual(r["quantidade_bruta"], 16)
        self.assertEqual(r["identidades_dia"], 12)
        self.assertEqual(r["repeticoes_mesmo_ponto_e_preco"],4)
        self.assertEqual(r["reenvios_deduplicados"],0)
        self.assertEqual(len(r["identidades_comparaveis"]),2)

    def test_midnight_utc_usa_calendario_de_mato_grosso(self):
        dia = date(2026,10,12)
        ts = datetime(2026,10,13,2,30,tzinfo=timezone.utc)
        rows=seis_dias(0)
        rows[0] = replace(rows[0], data_publicacao=ts,
                          data_coleta=ts+timedelta(minutes=10))
        r=analisar(rows, as_of=datetime(2026,10,19,2,tzinfo=timezone.utc))
        self.assertEqual(r["status"], "DESCRITIVO_OFFLINE_NAO_HOMOLOGADO")


if __name__=="__main__":
    unittest.main()
