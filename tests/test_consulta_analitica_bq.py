"""Contrato de consulta temporal do NIVON, com BigQuery simulado."""
import sys
import types
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from nivon.consulta_analitica_bq import consultar,planejar_consulta,ErroConsultaAnalitica


def mock_bigquery():
    bq=types.ModuleType("google.cloud.bigquery")
    bq.QueryJobConfig=lambda **kwargs: types.SimpleNamespace(**kwargs)
    bq.ScalarQueryParameter=lambda n,t,v:(n,t,v)
    cloud=types.ModuleType("google.cloud")
    cloud.bigquery=bq
    google=types.ModuleType("google")
    google.cloud=cloud
    return {"google":google,"google.cloud":cloud,"google.cloud.bigquery":bq}

class Job:
    def __init__(self,rows):
        self.rows=rows
    def result(self,timeout=None):
        return self.rows

class Client:
    def __init__(self,rows):
        self.rows=rows
        self.queries=[]
    def query(self,sql,job_config=None):
        self.queries.append((sql,job_config))
        return Job(self.rows)

ROW={
 "dataset_id":"BR_CCEE_PLD_HORARIO",
 "identidade":"202610|NORDESTE|23|00|529",
 "fingerprint":"a"*64,
 "data_referencia":date(2026,10,23),
 "competencia":"202610",
 "data_publicacao":None,
 "data_coleta":datetime(2026,10,23,3,0,tzinfo=timezone.utc),
 "natureza":"INFORMADO",
 "valor":"57.31","unidade":"R$/MWh",
 "campos":{"submercado":"NORDESTE","hora":0},
 "snapshot_id":"b"*64,
}
ARGS={
 "project_id":"nivon-data","dataset_id":"agro",
 "fonte":"BR_CCEE_PLD_HORARIO","inicio":"2026-10-01",
 "fim":"2026-10-23","as_of":"2026-10-23T12:00:00Z"
}

class ConsultaTemporalTest(unittest.TestCase):
    def testar(self,**mod):
        kwargs={**ARGS,**mod}
        cliente=kwargs.pop("client",Client([ROW]))
        with patch.dict(sys.modules,mock_bigquery()):
            return consultar(**kwargs,executar=True,client=cliente),cliente

    def test_plano_so_monta_sql(self):
        d=consultar(**ARGS)
        self.assertFalse(d["executado"])
        self.assertTrue(d["sql_parametrizado"])
        plano=planejar_consulta(**ARGS)
        self.assertIn("data_referencia BETWEEN @inicio AND @fim",plano["sql"])
        self.assertIn("data_coleta <= @as_of",plano["sql"])
        self.assertIn("data_publicacao <= @as_of",plano["sql"])
        self.assertIn("ROW_NUMBER() OVER",plano["sql"])

    def test_consulta_lida_preserva_unidade_proveniencia_e_asof(self):
        r,cliente=self.testar()
        self.assertEqual(r["quantidade"],1)
        self.assertTrue(r["executado"])
        self.assertEqual(r["observacoes"][0]["valor"],"57.31")
        self.assertEqual(r["observacoes"][0]["unidade"],"R$/MWh")
        self.assertEqual(r["observacoes"][0]["snapshot_id"],"b"*64)
        self.assertEqual(r["status"],"DADOS_INTERNOS_NAO_HOMOLOGADOS_EDITORIALMENTE")
        self.assertEqual(len(cliente.queries),1)
        sql,config=cliente.queries[0]
        self.assertIn("FROM `nivon-data.agro.nivon_observacoes`",sql)
        self.assertEqual(config.maximum_bytes_billed,100_000_000)
        self.assertTrue(config.use_query_cache)
        self.assertEqual(len(config.query_parameters),5)

    def test_resultado_vazio_e_publicacao_futura(self):
        r,_=self.testar(client=Client([]))
        self.assertTrue(r["sem_resultados"])
        self.assertEqual(r["quantidade"],0)
        com_futuro=dict(ROW,data_coleta=datetime(2026,10,24,tzinfo=timezone.utc))
        with self.assertRaises(ErroConsultaAnalitica):
            self.testar(client=Client([com_futuro]))

    def test_bloquear_identificadores_injecao_janelas_sem_limites(self):
        for invalido in (
            {"fonte":"PLD; DROP TABLE"},
            {"project_id":"wrong.project"},
            {"dataset_id":"dataset`"},
            {"inicio":"2022-01-01","fim":"2026-10-23"},
            {"as_of":"2026-10-23T12:00:00"},
            {"limite":10000},
            {"max_bytes_billed":10**12},
        ):
            with self.subTest(invalido=invalido), self.assertRaises(ErroConsultaAnalitica):
                planejar_consulta(**{**ARGS,**invalido})

    def test_serie_filtrada_no_sql_depois_da_revisao_asof(self):
        args = {**ARGS,"classe":"FRETE_ANUNCIADO","serie_id":"FRETE_EXEMPLO"}
        plano=planejar_consulta(**args)
        sql=plano["sql"]
        self.assertIn("FROM versoes WHERE posicao = 1 AND JSON_VALUE",sql)
        self.assertIn("JSON_VALUE(campos, '$.serie_id') = @serie_id",sql)
        self.assertLess(sql.index("JSON_VALUE(campos"),sql.index("LIMIT @limite"))
        x=dict(ROW,campos={"classe":"FRETE_ANUNCIADO","serie_id":"FRETE_EXEMPLO"})
        r,cliente=self.testar(client=Client([x]),classe="FRETE_ANUNCIADO",serie_id="FRETE_EXEMPLO")
        self.assertEqual(r["quantidade"],1)
        self.assertEqual(r["serie_id"],"FRETE_EXEMPLO")
        self.assertEqual(len(cliente.queries[0][1].query_parameters),7)
        with self.assertRaises(ErroConsultaAnalitica):
            self.testar(client=Client([ROW]),classe="FRETE_ANUNCIADO",serie_id="FRETE_EXEMPLO")

    def test_escopo_serie_obrigatorio_parametrizado(self):
        for extra in (
            {"classe":"FRETE_ANUNCIADO"},
            {"serie_id":"TESTE"},
            {"classe":"FRETE_ANUNCIADO","serie_id":"x' OR TRUE --"},
            {"classe":"FRETE_INDEVIDO","serie_id":"TESTE"},
        ):
            with self.subTest(extra=extra),self.assertRaises(ErroConsultaAnalitica):
                planejar_consulta(**{**ARGS,**extra})

    def test_sem_usar_fonte_errada(self):
        falso=dict(ROW,dataset_id="OUTRA_FONTE")
        with self.assertRaises(ErroConsultaAnalitica):
            self.testar(client=Client([falso]))

if __name__=="__main__":
    unittest.main()
