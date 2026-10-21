"""Cenários sintéticos R01: painel constante em 12 sessões antes da dinâmica."""
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from nivon.fretes_dinamica_r01 import dinamica_ofertas_pareadas
from nivon.fretes_painel_pr30 import ErroPainelFrete
from nivon.fretes_registros import OfertaFrete
from nivon.motor_tendencias import ErroTendencia

START = date(2026, 10, 1)
CUTOFF = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def oferta(j, i, preco):
    dia = START + timedelta(days=j)
    pub = datetime(dia.year, dia.month, dia.day, 15, tzinfo=timezone.utc)
    return OfertaFrete(
        publicacao_id=f"pub:{j}:{i}", registro_id=f"reg:{j}:{i}",
        oferta_id=f"oferta:{j}:{i}",
        municipio_ibge="5107925", destino_ibge="5107602",
        pickup_entity_id=f"ponto:{i}", transportadora_id=f"carrier:{i}",
        descarga_entity_id="terminal:um", produto="MILHO",
        equipamento="RODOTREM", regime="PJ",
        frete_base_brl_t=Decimal(str(preco)),
        pedagio_brl_t=Decimal("10"),
        frete_cheio_brl_t=Decimal(str(preco))+Decimal("10"),
        data_referencia=dia, data_publicacao=pub,
        data_coleta=pub+timedelta(minutes=10), fonte_id="FIXTURE",
    )


def linhas(valores):
    return [oferta(j,i,v+i*20) for j,v in enumerate(valores) for i in (1,2)]


def analisar(registros, **kwargs):
    opts={
        "origem_ibge":"5107925", "destino_ibge":"5107602",
        "descarga_entity_id":"terminal:um", "produto":"MILHO",
        "equipamento":"RODOTREM", "regime":"PJ", "pedagio":"ADICIONAL",
        "as_of":CUTOFF, "janela":6, "minimo_pares":2,
        "tolerancia_absoluta":2,
    }
    opts.update(kwargs)
    return dinamica_ofertas_pareadas(registros,**opts)


class TestDinamicaFretePareado(unittest.TestCase):
    def test_alta_ganha_forca_mesmos_pares(self):
        r=analisar(linhas([150,151,152,153,154,155,
                           156,159,162,165,168,171]))
        self.assertEqual(r["dinamica"],"AUMENTO_DE_FORCA")
        self.assertEqual(r["tendencia"],"ALTA")
        self.assertEqual(r["pares_comparaveis"],2)
        self.assertEqual(r["metodologia_painel"],"PARES_CONSTANTES_DUAS_JANELAS")
        self.assertEqual(len(r["cobertura_amostral"]),12)
        self.assertNotIn("serie_pareada",r)
        self.assertNotIn("frete_medio_municipal",str(r))
        self.assertFalse(r["publicavel"])
        self.assertIsNone(r["probabilidades_calibradas"])

    def test_baixa_perde_forca(self):
        r=analisar(linhas([190,186,182,178,174,170,
                           168,167,166,165,164,163]))
        self.assertEqual(r["dinamica"],"PERDA_DE_FORCA")
        self.assertEqual(r["tendencia"],"BAIXA")

    def test_reversao_alta_baixa_mesmos_pares(self):
        r=analisar(linhas([150,153,156,159,162,165,
                           165,162,159,156,153,150]))
        self.assertEqual(r["dinamica"],"REVERSAO_OBSERVADA")
        self.assertEqual(r["tendencia_anterior"],"ALTA")
        self.assertEqual(r["tendencia_atual"],"BAIXA")
        self.assertFalse(r["direitos_publicacao_verificados"])

    def test_estabilidade_persistente(self):
        r=analisar(linhas([150]*12))
        self.assertEqual(r["dinamica"],"ESTABILIDADE_PERSISTENTE")

    def test_participantes_rotativos_nao_viram_sinal_falso(self):
        rows=linhas([150]*12)
        for idx,item in enumerate(rows):
            j=idx//2
            if item.pickup_entity_id=="ponto:2":
                rows[idx]=replace(
                    item,
                    pickup_entity_id="rotativo:A" if j<6 else "rotativo:B",
                    transportadora_id="carrier:A" if j<6 else "carrier:B",
                    frete_base_brl_t=Decimal(100 if j<6 else 300),
                    frete_cheio_brl_t=Decimal(110 if j<6 else 310),
                )
        r=analisar(rows)
        self.assertEqual(r["status"],"PAINEL_INCOMPARAVEL")
        self.assertEqual(r["dinamica"],"INDETERMINADA")
        self.assertFalse(r["publicavel"])

    def test_participantes_novos_nao_alteram_sinal(self):
        rows=linhas([150]*12)
        for j in range(12):
            rows.append(replace(
                oferta(j,3,100 if j<6 else 500),
                pickup_entity_id="novo:A" if j<6 else "novo:B",
                transportadora_id="novo-carrier:A" if j<6 else "novo-carrier:B",
            ))
        r=analisar(rows)
        self.assertEqual(r["dinamica"],"ESTABILIDADE_PERSISTENTE")
        self.assertEqual(r["pares_comparaveis"],2)

    def test_reposts_identicos_nao_geram_novos_pares(self):
        rows=linhas([150]*12)
        for j in range(10):
            rows.append(replace(
                rows[0], registro_id=f"rep:{j}", oferta_id=f"rep:{j}",
                publicacao_id=f"rep_pub:{j}",
            ))
        r=analisar(rows)
        self.assertEqual(r["pares_comparaveis"],2)
        self.assertEqual(r["repeticoes_mesmo_ponto_e_preco"],10)
        self.assertEqual(r["identidades_dia"],24)

    def test_mesma_identidade_preco_diferente_rejeita(self):
        rows=linhas([150]*12)
        rows.append(replace(
            rows[0], registro_id="novo:id", oferta_id="nova:oferta",
            publicacao_id="pub:nova", frete_base_brl_t=Decimal(999),
            frete_cheio_brl_t=Decimal(1009),
        ))
        with self.assertRaisesRegex(ErroPainelFrete,"conflitantes"):
            analisar(rows)

    def test_11_dias_nao_sao_suficientes(self):
        r=analisar(linhas([150]*11))
        self.assertEqual(r["status"],"DADOS_INSUFICIENTES")
        self.assertEqual(r["dinamica"],"INDETERMINADA")

    def test_uma_sessao_no_meio_ausente_bloqueia(self):
        rows=[x for x in linhas([150]*12) if x.data_referencia!=START+timedelta(days=6)]
        # Onze datas distintas => sem janela completa.
        r=analisar(rows)
        self.assertEqual(r["status"],"DADOS_INSUFICIENTES")
        self.assertEqual(r["dinamica"],"INDETERMINADA")

    def test_publicacao_apos_corte_rejeitada(self):
        rows=linhas([150]*12)
        with self.assertRaisesRegex(ErroPainelFrete,"futura"):
            analisar(rows,as_of=datetime(2026,10,12,12,tzinfo=timezone.utc))

    def test_mistura_de_descarga_rejeitada(self):
        rows=linhas([150]*12)
        rows[3]=replace(rows[3],descarga_entity_id="terminal:outro")
        with self.assertRaisesRegex(ErroPainelFrete,"mistura"):
            analisar(rows)

    def test_nao_aceita_data_sem_timezone(self):
        with self.assertRaisesRegex(ErroTendencia,"fuso"):
            analisar(linhas([150]*12),as_of=datetime(2026,10,15,12))

    def test_janela_ou_limiar_invalidos(self):
        for n in (3,25,True):
            with self.subTest(janela=n),self.assertRaises(ErroTendencia):
                analisar(linhas([150]*12),janela=n)
        with self.assertRaises(ErroTendencia):
            analisar(linhas([150]*12),mudanca_minima_forca_em_limiares=0)

    def test_nunca_alega_previsao_ou_contrato(self):
        r=analisar(linhas([150]*12))
        self.assertEqual(r["orientacao"],"OBSERVADA")
        self.assertEqual(r["valor_analisado"],"FRETE_BASE_ANUNCIADO_SEM_PEDAGIO")
        self.assertEqual(r["homologacao_origem"],"PENDENTE")
        self.assertNotIn("previsao_7_dias",r)
        self.assertNotIn("valor_contratado",r)


if __name__=="__main__":
    unittest.main()
