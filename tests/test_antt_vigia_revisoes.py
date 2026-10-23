"""Regressões do vigia ANTT: zero escritas, revisões e falhas fechadas."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from nivon.antt_vigia_revisoes import (
    MAX_BYTES_QUERY, comparar_staging_bq, _consulta_bq
)
from nivon.transporte_multimodal import ErroTransporte


SHA_A="a"*64
SHA_B="b"*64


def meta(ano):
    return [], {"ano":ano, "sha256":SHA_A, "registros":10,
                 "toneladas_uteis":"122.4","competencia_maxima":f"{ano}-08"}


def bq(ano=2026, *, sha=SHA_A, total="122.4", n=10, versoes=1):
    return {"ano":ano,"sha256":sha,"registros":n,
            "toneladas_uteis":total,"competencia_maxima":f"{ano}-08",
            "versoes":versoes}


class FakeSDK:
    class QueryJobConfig:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class ArrayQueryParameter:
        def __init__(self, name, kind, values):
            self.name, self.kind, self.values = name, kind, values


class FakeClient:
    def __init__(self,rows):
        self.rows=rows
        self.called=[]
    def query(self,sql,job_config):
        self.called.append((sql,job_config))
        return SimpleNamespace(result=lambda timeout: [SimpleNamespace(items=lambda:dict(r).items()) for r in self.rows])


class VigiaTest(unittest.TestCase):
    def test_mesmo_sha_e_totais(self):
        with patch("nivon.antt_vigia_revisoes.montar_lote",side_effect=lambda s,y:meta(y)):
            r=comparar_staging_bq(staging="/nao-acessado",anos=[2026],resumos_bq=[bq()])
        self.assertEqual(r["estado"],"FONTES_SEM_REVISAO_PENDENTE")
        self.assertFalse(r["escrita_cloud_executada"])
        self.assertEqual(r["anos_com_diferenca"],[])

    def test_sha_novo_nao_recarrega_automaticamente(self):
        with patch("nivon.antt_vigia_revisoes.montar_lote",side_effect=lambda s,y:meta(y)):
            r=comparar_staging_bq(staging="fake",anos=[2026],resumos_bq=[bq(sha=SHA_B)])
        self.assertEqual(r["estado"],"REVISAR_FONTE_ANTES_DE_PUBLICAR")
        self.assertEqual(r["anos_com_diferenca"],[2026])
        self.assertEqual(r["resultados"][0]["estado"],"NOVA_REVISAO_OFICIAL_NAO_CARREGADA")
        self.assertFalse(r["recarregamento_automatico_autorizado"])

    def test_mesmo_sha_com_soma_errada_e_erro_forte(self):
        with patch("nivon.antt_vigia_revisoes.montar_lote",side_effect=lambda s,y:meta(y)):
            r=comparar_staging_bq(staging="fake",anos=[2026],resumos_bq=[bq(total="120")])
        self.assertEqual(r["resultados"][0]["estado"],"MESMO_SHA_TOTAIS_DIVERGENTES_BLOQUEIO")

    def test_ano_ausente_nao_equivale_a_zero(self):
        with patch("nivon.antt_vigia_revisoes.montar_lote",side_effect=lambda s,y:meta(y)):
            r=comparar_staging_bq(staging="fake",anos=[2025,2026],resumos_bq=[bq()])
        self.assertEqual(r["anos_com_diferenca"],[2025])
        self.assertEqual(r["resultados"][0]["estado"],"ANO_AUSENTE_BQ_NAO_CARREGAR_AUTOMATICAMENTE")

    def test_multiplas_versoes_ativas_falha_fechada(self):
        with self.assertRaises(ErroTransporte):
            comparar_staging_bq(staging="fake",anos=[2026],resumos_bq=[bq(versoes=2)])
        with self.assertRaises(ErroTransporte):
            comparar_staging_bq(staging="fake",anos=[2026],resumos_bq=[bq(),bq()])

    def test_comparacao_nao_aceita_outros_anos(self):
        with self.assertRaises(ErroTransporte):
            comparar_staging_bq(staging="fake",anos=[2026],resumos_bq=[bq(2025)])
        with self.assertRaises(ErroTransporte):
            comparar_staging_bq(staging="fake",anos=[2026,2026],resumos_bq=[])

    def test_consulta_somente_select_limitada_50mb(self):
        client=FakeClient([bq()])
        out=_consulta_bq(projeto="nivon-data",dataset="nivon_raw",anos=[2026],
                         cliente=client,sdk=FakeSDK)
        self.assertEqual(len(out),1)
        sql,cfg=client.called[0]
        self.assertTrue(sql.startswith("SELECT ano,"))
        self.assertIn("vw_antt_ferrovia_od_atual",sql)
        self.assertIn("UNNEST(@anos)",sql)
        self.assertEqual(cfg.maximum_bytes_billed,MAX_BYTES_QUERY)
        self.assertEqual(cfg.query_parameters[0].values,[2026])

    def test_bloquear_outro_projeto_sem_query(self):
        client=FakeClient([bq()])
        with self.assertRaises(ErroTransporte):
            _consulta_bq(projeto="outroprojeto",dataset="nivon_raw",anos=[2026],
                         cliente=client,sdk=FakeSDK)
        self.assertEqual(client.called,[])


if __name__=="__main__":
    unittest.main()
