"""Testes de contrato de interop Mercados/Quant e fretes individuais."""
import unittest
from copy import deepcopy
from datetime import date, timedelta
from nivon.rolling_origin import executar_rolling_origin_asof
from nivon.quant_core import ErroQuantitativo
from nivon.integracao_contratos_quant import normalizar_relatorio_brier_mercados
from nivon.integracao_frete_quant import preparar_serie_frete_anunciado

KEY={
    "municipio_ibge":"5107925","pickup_entity_id":"PONTO_A",
    "transportadora_id":"TR_1","destino_ibge":"5107602",
    "descarga_entity_id":"DEST_1","produto":"MILHO","equipamento":"RODOTREM","regime":"PJ",
}
def frete(**changes):
    r={**KEY,
       "registro_id":"REG_1","oferta_id":"OFERTA_1",
       "natureza":"FRETE_ANUNCIADO_NAO_CONTRATADO",
       "fonte_id":"TRANSPORTADORA_TESTE",
       "frete_base_brl_t":"150.00","pedagio_brl_t":"10.00",
       "frete_cheio_brl_t":"160.00",
       "data_referencia":"2026-10-19",
       "data_publicacao":"2026-10-19T10:00:00-04:00",
       "data_coleta":"2026-10-19T11:00:00-04:00"}
    r.update(changes)
    return r
def preparar(rows,**kwargs):
    options=dict(chave=KEY,fonte_id="TRANSPORTADORA_TESTE",
                 tipo_valor="CHEIO",as_of="2026-10-21T20:00:00Z")
    options.update(kwargs)
    return preparar_serie_frete_anunciado(rows,**options)
def relatorio():
    return {
        "status":"BACKTEST_TEMPORAL_OFFLINE_NAO_HOMOLOGADO",
        "serie_id":"CME:SOJA:2026-11:AJUSTE:USC/BU",
        "modelo_versao":"modelo_teste","regra_rotulagem":"banda_1pct",
        "horizonte_sessoes":1,"amostra_total":52,"avaliacoes":30,
        "brier_multiclasse":0.06,"brier_benchmark_expansivo":0.24,
        "skill_brier_vs_benchmark":0.75,
        "logloss_media":0.4,"ece_confianca":0.1,
        "bins_calibracao":[{"faixa":[.75,1],"n":30,"confianca_media":.8,"acerto":.7}],
        "probabilidades_calibradas":None,"publicavel":False,
    }


class PonteMercados(unittest.TestCase):
    def test_conversao_exata_brier_e_skill(self):
        v=normalizar_relatorio_brier_mercados(relatorio())
        self.assertAlmostEqual(v["brier_multiclasse_medio"],.02)
        self.assertAlmostEqual(v["brier_benchmark_expansivo_medio"],.08)
        self.assertAlmostEqual(v["skill_brier_vs_benchmark"],.75)
        self.assertEqual(v["convencao_brier"],"SOMA_ERROS_QUADRATICOS_DIVIDIDA_POR_3")
        self.assertFalse(v["publicavel"])

    def test_bloqueia_relatorio_incompleto_publicavel_ou_calibrado(self):
        for k,v in (
            ("status","AMOSTRA_OOS_INSUFICIENTE"),
            ("publicavel",True),("probabilidades_calibradas",{"ALTA":.7}),
            ("avaliacoes",4),("brier_multiclasse",2.1),
            ("skill_brier_vs_benchmark",.4),
            ("ece_confianca",float("nan")),
        ):
            r=relatorio();r[k]=v
            with self.subTest(k=k),self.assertRaises(ErroQuantitativo):
                normalizar_relatorio_brier_mercados(r)

    def test_bins_incompletos_e_ganho_indefinido(self):
        r=relatorio();r["bins_calibracao"][0]["n"]=29
        with self.assertRaises(ErroQuantitativo):
            normalizar_relatorio_brier_mercados(r)
        r=relatorio();r["brier_benchmark_expansivo"]=0.0
        r["skill_brier_vs_benchmark"]=None
        self.assertIsNone(normalizar_relatorio_brier_mercados(r)["skill_brier_vs_benchmark"])


class PonteFretes(unittest.TestCase):
    def test_formato_pr18_sem_sha_bloqueia_uso_preditivo(self):
        r=preparar([frete()])
        self.assertEqual(r["status"],"BLOQUEADO_SHA_EDICAO_AUSENTE")
        self.assertEqual(r["observacoes_asof"],[])
        self.assertFalse(r["publicavel"])

    def test_serie_por_entidade_sem_media_municipal(self):
        r=preparar([
            frete(edicao_sha256="a"*64),
            frete(registro_id="REG_2",oferta_id="OFERTA_2",
                  data_referencia="2026-10-20",frete_base_brl_t="155.00",
                  frete_cheio_brl_t="165.00",
                  data_publicacao="2026-10-20T10:00:00-04:00",
                  data_coleta="2026-10-20T11:00:00-04:00",
                  edicao_sha256="b"*64)
        ])
        self.assertEqual(r["registros"],2)
        self.assertEqual([x["valor"] for x in r["observacoes_asof"]],[160.0,165.0])
        self.assertTrue(all(x["serie_id"]==r["serie_id"] for x in r["observacoes_asof"]))
        self.assertNotIn("media_municipal",r)
        self.assertFalse(r["publicavel"])

    def test_identidade_e_condicoes_sem_preco_municipal(self):
        for campo,valor in (("pickup_entity_id","PONTO_B"),
                            ("transportadora_id","TR_2"),
                            ("descarga_entity_id","DEST_2"),
                            ("regime","PF"),("equipamento","BITREM"),
                            ("produto","SOJA"),("municipio_ibge","5100000")):
            row=frete(edicao_sha256="a"*64)
            row[campo]=valor
            with self.subTest(campo=campo),self.assertRaisesRegex(ErroQuantitativo,"heterogeneas"):
                preparar([row])

    def test_revisao_muda_vintage_no_mesmo_dia_sem_recalcular_media(self):
        a=frete(edicao_sha256="a"*64)
        b=frete(edicao_sha256="b"*64,registro_id="REG_2",
                frete_base_brl_t="158.00",frete_cheio_brl_t="168.00",
                data_publicacao="2026-10-19T12:00:00-04:00",
                data_coleta="2026-10-19T13:00:00-04:00")
        out=preparar([a,b])
        self.assertEqual(out["registros"],2)
        self.assertEqual([x["periodo"] for x in out["observacoes_asof"]],["2026-10-19"]*2)
        self.assertEqual([x["valor"] for x in out["observacoes_asof"]],[160,168])

    def test_recusa_composicao_incompativel_pedagio_preco_e_fonte(self):
        for change in ({"pedagio_brl_t":None},
                       {"frete_cheio_brl_t":"999"},
                       {"fonte_id":"OUTRO"},
                       {"natureza":"CONTRATADO"}):
            with self.subTest(change=change),self.assertRaises(ErroQuantitativo):
                preparar([frete(edicao_sha256="a"*64,**change)])

    def test_temporalidade_falha_e_hash_conflict(self):
        a=frete(edicao_sha256="a"*64)
        for bad in (
            frete(edicao_sha256="a"*64,data_coleta="2026-10-22T10:00:00Z"),
            frete(edicao_sha256="a"*64,data_coleta="2026-10-19T09:00:00-04:00"),
        ):
            with self.assertRaises(ErroQuantitativo): preparar([bad])
        b=frete(edicao_sha256="b"*64,registro_id="REG_2",frete_base_brl_t="180",
                frete_cheio_brl_t="190")
        with self.assertRaisesRegex(ErroQuantitativo,"conflitantes"):
            preparar([a,b])

    def test_sha_fornecido_alimenta_rolling_origin_sem_media_municipal(self):
        dias=[(date(2026,10,1)+timedelta(days=i)).isoformat() for i in range(15)]
        eventos=[]
        for i,d in enumerate(dias):
            eventos.append(frete(
                registro_id=f"REG_{i}",oferta_id=f"OFERTA_{i}",
                edicao_sha256=("%064x" % (i+1)),
                frete_base_brl_t=str(150+i)+".00",
                frete_cheio_brl_t=str(160+i)+".00",
                data_referencia=d,data_publicacao=d+"T10:00:00-04:00",
                data_coleta=d+"T11:00:00-04:00"))
        norm=preparar(eventos)
        self.assertTrue(norm["asof_pronto"])
        self.assertEqual(len(norm["observacoes_asof"]),15)
        origens={dias[i]:dias[i]+"T18:00:00Z" for i in (6,7,8,9,10)}
        result=executar_rolling_origin_asof(
            norm["observacoes_asof"],calendario=dias,origens_em=origens,
            as_of_avaliacao="2026-10-21T20:00:00Z",
            serie_id=norm["serie_id"],unidade="BRL/T",
            fonte_id="TRANSPORTADORA_TESTE",modelo_id="PERSISTENCIA_MAIS_UM_TESTE",
            horizonte_periodos=1,tamanho_treino=5,
            modelo=lambda treino,ctx:treino[-1]["valor"]+1,
            min_folds=5,tolerancia_absoluta=0.5)
        self.assertEqual(result["n_folds"],5)
        self.assertEqual(result["metricas"]["mae"],0.0)
        self.assertEqual(result["metricas"]["mae_baseline"],1.0)
        self.assertFalse(result["publicavel"])

    def test_overflow_e_subfluxo_decimal_bloqueados(self):
        for valor in ("1e9999","1e-9999"):
            with self.subTest(valor=valor),self.assertRaises(ErroQuantitativo):
                preparar([frete(edicao_sha256="a"*64,
                               frete_base_brl_t=valor,
                               frete_cheio_brl_t=valor,
                               pedagio_brl_t="0")])

    def test_reutilizacao_de_registro_id_com_preco_alterado_bloqueada(self):
        a=frete(edicao_sha256="a"*64)
        b=frete(edicao_sha256="b"*64,
                data_publicacao="2026-10-19T12:00:00-04:00",
                data_coleta="2026-10-19T13:00:00-04:00",
                frete_base_brl_t="151",frete_cheio_brl_t="161")
        with self.assertRaisesRegex(ErroQuantitativo,"registro_id reutilizado"):
            preparar([a,b])

    def test_repeticao_mesma_coleta_identica_nao_pesa_duas_vezes(self):
        row=frete(edicao_sha256="a"*64)
        self.assertEqual(preparar([row,deepcopy(row)])["registros"],1)


if __name__=="__main__":
    unittest.main()
