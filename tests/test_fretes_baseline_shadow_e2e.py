"""E2E de emissão shadow assinada por atestador MOCK e avaliação futura.

As propostas não são previsões verificadas em tempo externo nem dados reais.
"""
import sqlite3
import unittest
from datetime import datetime,timedelta,timezone

from nivon.fretes_baseline_shadow import (
    MODELO_BASELINE_ZERO,preparar_intencoes_baseline_frete,
)
from nivon.fretes_previsoes_arquivadas import ErroAvaliacaoFrete
from nivon.fretes_ledger_persistente import (
    GENESIS,inicializar_ledger_frete,anexar_lote_previsoes_frete,
    avaliar_ledger_frete,verificar_ledger_frete,
)
from test_fretes_previsoes_arquivadas import (
    KEY,BASE,CUTOFF,PARAMS,SOURCE,historico,assinar,
)


def intencoes(rows,j,horizontes=(7,30,90)):
    dia=BASE+timedelta(days=j)
    emitido=datetime(dia.year,dia.month,dia.day,16,tzinfo=timezone.utc)
    disponiveis=[x for x in rows if x.data_coleta<=emitido]
    return preparar_intencoes_baseline_frete(
        disponiveis,emitido_em=emitido,fonte_id=SOURCE,
        emissor_id="fixture-archive",horizontes_dias=horizontes,**PARAMS,
    )


def assinar_mock(proposta):
    p={**proposta}
    p["registrado_em"]=(
        datetime.fromisoformat(p["emitido_em"])+timedelta(minutes=1)
    ).isoformat()
    return assinar(p)


class TestShadowBaselineFretesE2E(unittest.TestCase):
    def test_emissao_7_30_90_com_hmac_externo_e_mae_nao_zero(self):
        rows=historico(110)
        predicoes=[]
        for j in range(1,6):
            ret=intencoes(rows,j)
            self.assertEqual(ret["status"],"INTENCOES_BASELINE_SHADOW_NAO_ASSINADAS")
            self.assertFalse(ret["assinaturas_criadas"])
            self.assertFalse(ret["persistencia_realizada"])
            self.assertEqual(ret["pares_origem"],2)
            for proposta in ret["previsoes_para_assinatura_externa"]:
                self.assertEqual(proposta["delta_previsto_brl_t"],"0")
                self.assertNotIn("assinatura_hmac_sha256",proposta)
                self.assertNotIn("registrado_em",proposta)
                predicoes.append(assinar_mock(proposta))
        predicoes.sort(key=lambda p:(p["registrado_em"],p["horizonte_dias_corridos"]))
        with sqlite3.connect(":memory:") as db:
            inicializar_ledger_frete(db)
            ret=anexar_lote_previsoes_frete(
                db,predicoes,
                recebimentos=[datetime.fromisoformat(p["registrado_em"])+timedelta(seconds=2)
                              for p in predicoes],
                cabeca_anterior_sha256=GENESIS,chave_verificacao=KEY,
                emissor_esperado="fixture-archive",
            )
            v=verificar_ledger_frete(
                db,cabeca_esperada_sha256=ret["cabeca_sha256"],
                chave_verificacao=KEY,emissor_esperado="fixture-archive",
            )
            self.assertEqual(v["quantidade"],15)
            for h in (7,30,90):
                result=avaliar_ledger_frete(
                    db,rows,cabeca_esperada_sha256=ret["cabeca_sha256"],
                    chave_verificacao=KEY,emissor_esperado="fixture-archive",
                    as_of=CUTOFF,fonte_id=SOURCE,
                    modelo_versao=MODELO_BASELINE_ZERO,
                    horizonte_dias_corridos=h,**PARAMS,
                )
                self.assertEqual(result["n_previsoes_declaradas"],5)
                self.assertEqual(result["mae_brl_t"],h)
                self.assertEqual(result["mae_baseline_zero_brl_t"],h)
                self.assertEqual(result["ganho_mae_vs_zero"],0)
                self.assertFalse(result["publicavel"])
                self.assertFalse(result["ancora_temporal_independente_comprovada"])

    def test_dados_do_alvo_no_payload_bloqueiam_previsao_retroativa(self):
        rows=historico(110)
        j=1
        dia=BASE+timedelta(days=j)
        emitido=datetime(dia.year,dia.month,dia.day,16,tzinfo=timezone.utc)
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"posteriores"):
            preparar_intencoes_baseline_frete(
                rows,emitido_em=emitido,fonte_id=SOURCE,
                emissor_id="fixture-archive",**PARAMS,
            )

    def test_dia_sem_duas_identidades_bloqueado(self):
        rows=historico(20)
        j=8
        dia=BASE+timedelta(days=j)
        disponivel=[x for x in rows if x.data_referencia<dia or
                    x.data_referencia==dia and x.pickup_entity_id=="ponto:1"]
        emitido=datetime(dia.year,dia.month,dia.day,16,tzinfo=timezone.utc)
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"pares comparáveis"):
            preparar_intencoes_baseline_frete(
                disponivel,emitido_em=emitido,fonte_id=SOURCE,
                emissor_id="fixture-archive",**PARAMS,
            )

    def test_mesma_origem_mesmo_contrato_gera_mesmos_ids(self):
        rows=historico(20)
        a=intencoes(rows,8)
        b=intencoes(list(reversed(rows)),8)
        self.assertEqual(a["previsoes_para_assinatura_externa"],
                         b["previsoes_para_assinatura_externa"])
        ids=[x["previsao_id"] for x in a["previsoes_para_assinatura_externa"]]
        self.assertEqual(len(set(ids)),3)

    def test_horizontes_invalidos_rejeitados(self):
        rows=historico(20)
        for hs in ((30,7),(7,7),(True,),(),(366,),[7,30,90]):
            with self.subTest(hs=hs),self.assertRaises(ErroAvaliacaoFrete):
                intencoes(rows,8,horizontes=hs)

    def test_dois_produtos_ou_fontes_nao_sao_mesclados(self):
        rows=historico(20)
        from dataclasses import replace
        bad=list(rows)
        bad[0]=replace(bad[0],fonte_id="OUTRA-FONTE")
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"mistura de fontes"):
            intencoes(bad,8)

    def test_comissao_de_frete_nao_e_gerada_pelo_baseline(self):
        r=intencoes(historico(20),8)
        self.assertFalse(r["publicavel"])
        self.assertIsNone(r["probabilidades_calibradas"])
        for p in r["previsoes_para_assinatura_externa"]:
            self.assertNotIn("frete_medio_municipio",str(p))
            self.assertNotIn("volume_transportado",str(p))
            self.assertEqual(p["modelo_versao"],MODELO_BASELINE_ZERO)


if __name__=="__main__":
    unittest.main()
