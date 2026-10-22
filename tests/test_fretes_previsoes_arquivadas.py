"""Sem dados reais: HMAC de forecast, base point-in-time e alvo pareado."""
import hmac
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256

from nivon.fretes_atestacoes import serializacao_canonica
from nivon.fretes_previsoes_arquivadas import (
    DOMINIO, ErroAvaliacaoFrete, preparar_compromisso_base_frete,
    avaliar_previsoes_arquivadas_frete,
)
from nivon.fretes_registros import OfertaFrete
from nivon.fretes_painel_pr30 import ErroPainelFrete

KEY = b"simulated-archive-independent-hmac-key-20261021"
BASE = date(2026,4,1)
CUTOFF = datetime(2026,10,1,16,tzinfo=timezone.utc)
PARAMS = dict(
    origem_ibge="5107925", destino_ibge="5107602",
    descarga_entity_id="terminal:teste", produto="MILHO",
    equipamento="RODOTREM", regime="PJ", pedagio="ADICIONAL",
)
SOURCE="FIXTURE-RECEBIDA"
MODEL="mock-1"


def oferta(j,i,**kw):
    dia=BASE+timedelta(days=j)
    pub=datetime(dia.year,dia.month,dia.day,15,tzinfo=timezone.utc)
    valor=Decimal(200+j+i*10)
    row=dict(publicacao_id=f"p:{j}:{i}",registro_id=f"r:{j}:{i}",
             oferta_id=f"o:{j}:{i}",municipio_ibge="5107925",
             destino_ibge="5107602",pickup_entity_id=f"ponto:{i}",
             transportadora_id=f"carrier:{i}",descarga_entity_id="terminal:teste",
             produto="MILHO",equipamento="RODOTREM",regime="PJ",
             frete_base_brl_t=valor,pedagio_brl_t=Decimal(10),
             frete_cheio_brl_t=valor+Decimal(10),
             data_referencia=dia,data_publicacao=pub,
             data_coleta=pub+timedelta(minutes=10),fonte_id=SOURCE)
    row.update(kw)
    return OfertaFrete(**row)


def historico(dias=125):
    return [oferta(j,i) for j in range(dias) for i in (1,2)]


def assinar(p):
    payload=dict(p)
    payload["assinatura_hmac_sha256"]=hmac.new(
        KEY, DOMINIO+serializacao_canonica(p),sha256
    ).hexdigest()
    return payload


def emissao(rows,j,h=7,pred=None):
    origem=BASE+timedelta(days=j)
    dt=datetime(origem.year,origem.month,origem.day,16,tzinfo=timezone.utc)
    snap=preparar_compromisso_base_frete(
        rows,data_origem=origem.isoformat(),emitido_em=dt.isoformat(),**PARAMS)
    assert snap["pares_base"]==2
    p={
       **PARAMS,
       "previsao_id":f"prediction:{j}:{h}", "emissor_id":"fixture-archive",
       "fonte_id":SOURCE,"modelo_versao":MODEL,
       "data_origem":origem.isoformat(),
       "data_alvo":(origem+timedelta(days=h)).isoformat(),
       "horizonte_dias_corridos":h,
       "emitido_em":dt.isoformat(),
       "registrado_em":(dt+timedelta(minutes=1)).isoformat(),
       "treinado_ate":(dt-timedelta(minutes=1)).isoformat(),
       "delta_previsto_brl_t":str(h if pred is None else pred),
       "base_snapshot_sha256":snap["base_snapshot_sha256"],
    }
    return assinar(p)


def avaliar(rows,forecasts,**kw):
    params=dict(**PARAMS,fonte_id=SOURCE,modelo_versao=MODEL,
                horizonte_dias_corridos=7,as_of=CUTOFF,
                chave_verificacao=KEY,emissor_esperado="fixture-archive")
    params.update(kw)
    return avaliar_previsoes_arquivadas_frete(rows,forecasts,**params)


class TestPrevisoesArquivadasFrete(unittest.TestCase):
    def test_assinadas_7_dias_compara_baseline_zero(self):
        rows=historico(30)
        preds=[emissao(rows,j) for j in range(1,7)]
        r=avaliar(rows,preds)
        self.assertEqual(r["n_previsoes_declaradas"],6)
        self.assertEqual(r["horizonte_dias_corridos"],7)
        self.assertEqual(r["mae_brl_t"],0)
        self.assertEqual(r["mae_baseline_zero_brl_t"],7)
        self.assertEqual(r["ganho_mae_vs_zero"],1)
        self.assertTrue(r["hmac_conferido"])
        self.assertTrue(r["vies_de_sobrevivencia_do_painel_avaliado"])
        self.assertFalse(r["carimbo_temporal_externo_comprovado"])
        self.assertFalse(r["habilitado_para_producao"])
        self.assertIsNone(r["probabilidades_calibradas"])
        self.assertFalse(r["publicavel"])

    def test_horizontes_corridos_30_e_90(self):
        for h in (30,90):
            rows=historico(110)
            ps=[emissao(rows,j,h) for j in range(1,6)]
            r=avaliar(rows,ps,horizonte_dias_corridos=h)
            self.assertEqual(r["mae_baseline_zero_brl_t"],h)
            self.assertEqual(r["horizonte_dias_corridos"],h)

    def test_assinatura_falsificada_rejeitada(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        ps[2]["delta_previsto_brl_t"]="900"
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"assinatura"):
            avaliar(rows,ps)

    def test_chave_de_outro_emissor_rejeitada(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"assinatura"):
            avaliar(rows,ps,chave_verificacao=b"um-outro-servico-nao-autorizado-00000001")

    def test_snapshot_inconsistente_bloqueia_mesmo_resignado(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        p=dict(ps[0]);p.pop("assinatura_hmac_sha256")
        p["base_snapshot_sha256"]="a"*64
        ps[0]=assinar(p)
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"snapshot"):
            avaliar(rows,ps)

    def test_captura_posterior_a_emissao_nao_conta_para_base(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        rows[2]=replace(rows[2],data_coleta=rows[2].data_coleta+timedelta(hours=2))
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"painel de origem insuficiente na emissão"):
            avaliar(rows,ps)

    def test_falta_de_par_no_alvo_rejeita_lote_inteiro(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        # j=1 => alvo j=8. Remover um par não pode virar seleção de folds.
        rows=[x for x in rows if not (x.data_referencia==BASE+timedelta(days=8)
                                      and x.pickup_entity_id=="ponto:2")]
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"alvo sem pares"):
            avaliar(rows,ps)

    def test_fonte_de_um_par_trocada_rejeita(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        rows[16]=replace(rows[16],fonte_id="OUTRA")
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"fonte"):
            avaliar(rows,ps)

    def test_emissao_retroativa_nao_corrige_forecast(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        p=dict(ps[0]);p.pop("assinatura_hmac_sha256")
        p["emitido_em"]=(datetime(2026,4,9,16,tzinfo=timezone.utc)).isoformat()
        ps[0]=assinar(p)
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"registrada|corte"):
            avaliar(rows,ps)

    def test_registrado_apos_o_alvo_rejeita(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        p=dict(ps[0]);p.pop("assinatura_hmac_sha256")
        p["registrado_em"]=(datetime(2026,4,10,16,tzinfo=timezone.utc)).isoformat()
        ps[0]=assinar(p)
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"registrada"):
            avaliar(rows,ps)

    def test_duplicacao_de_previsao_id_rejeitada(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        ps[1]=dict(ps[0])
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"duplicado"):
            avaliar(rows,ps)

    def test_corte_antes_do_resultado_rejeita(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        with self.assertRaises((ErroPainelFrete,ErroAvaliacaoFrete)):
            avaliar(rows,ps,as_of=datetime(2026,4,6,17,tzinfo=timezone.utc))

    def test_divergencia_de_regime_rejeita(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        p=dict(ps[1]);p.pop("assinatura_hmac_sha256")
        p["regime"]="PF";ps[1]=assinar(p)
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"mistura"):
            avaliar(rows,ps)

    def test_limites_de_amostra_e_horizonte(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,5)]
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"histórico"):
            avaliar(rows,ps)
        for h in (True,0,366,7.0):
            with self.subTest(h=h),self.assertRaises(ErroAvaliacaoFrete):
                avaliar(rows,ps,horizonte_dias_corridos=h)

    def test_horizonte_declarado_float_reassinado_ainda_bloqueia(self):
        rows=historico(30)
        preds=[emissao(rows,j) for j in range(1,6)]
        for falso in (7.0,):
            p=dict(preds[0]);p.pop("assinatura_hmac_sha256")
            p["horizonte_dias_corridos"]=falso
            preds[0]=assinar(p)
            with self.assertRaisesRegex(ErroAvaliacaoFrete,"inteiro exato"):
                avaliar(rows,preds)

    def test_preco_anunciado_nao_preco_contratado(self):
        rows=historico(30)
        ps=[emissao(rows,j) for j in range(1,6)]
        r=avaliar(rows,ps)
        self.assertEqual(r["unidade"],"BRL/T_DESLOCAMENTO_DE_OFERTA_BASE")
        self.assertTrue(all(x["pares_comparaveis"]==2 for x in r["folds"]))
        self.assertNotIn("frete_contratado",str(r))
        self.assertNotIn("carga_transportada",str(r))


if __name__=="__main__":
    unittest.main()
