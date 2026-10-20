"""Integrações reais dos extras IVO. Sem coleta/rede: roda somente se extras instalados.

Esses testes são ignorados na CI básica (stdlib-only); não instalar libs
automaticamente em pull requests. Para homologar, testar os extras em sandbox
com recursos, licenças e versões explicitamente revisados.
"""
import importlib.util
import tempfile
import unittest
from datetime import date,datetime,timezone
from pathlib import Path

from nivon.historico import Observacao
from nivon.ivo_duckdb_adapter import carregar_asof_parquet
from nivon.ivo_mlforecast_adapter import prever_mlforecast_asof
from nivon.ivo_river_adapter import replay_river

UTC=timezone.utc


def installed(*modules):
    return all(importlib.util.find_spec(m) is not None for m in modules)


class TestIVOExtrasReais(unittest.TestCase):
    @unittest.skipUnless(installed("pandas","sklearn","mlforecast"),"Instale .[ivo-ml] em sandbox")
    def test_mlforecast_real_ridge_lags(self):
        dados=[]
        for y in range(2020,2027):
            for m in range(1,13):
                if (y,m)>(2026,4):
                    break
                ya=y+(m==12); ma=m%12+1
                dados.append(Observacao(
                    fonte="CONAB",variavel="VOLUME",produto="SOJA",regiao="MT",
                    unidade="t",calendario="MENSAL",competencia=f"{y}-{m:02d}",
                    referencia=date(y,m,1),publicacao=date(ya,ma,3),
                    coleta=datetime(ya,ma,4,tzinfo=UTC),
                    valor=float(100+(y-2020)*5+m*2)))
        r=prever_mlforecast_asof(dados,periodo_alvo="2026-06",
            fonte="CONAB",variavel="VOLUME",produto="SOJA",regiao="MT",unidade="t",
            dados_autorizados=True)
        self.assertEqual(r["modelo"],"MLFORECAST_RIDGE_LAGS_1_2_3_12")
        self.assertFalse(r["backend_de_teste_injetado"])
        self.assertFalse(r["modelo_homologado"])
        self.assertGreater(r["estimativa"],0.)

    @unittest.skipUnless(installed("river"),"Instale .[ivo-online] em sandbox")
    def test_river_real_prequential(self):
        rows=[]
        for i in range(1,6):
            pre_y,pre_m=(2024,12) if i==1 else (2025,i-1)
            pub_y,pub_m=2025,i+1
            rows.append({
                "modelo_id":"L1","versao_modelo":"V1",
                "indicador":"VOLUME","geografia":"MT","unidade":"t",
                "fonte_verdade":"CONAB","horizonte_meses":1,
                "previsao_id":f"P{i}","observacao_id":f"O{i}",
                "periodo":f"2025-{i:02d}",
                "previsao_emitida_em":datetime(pre_y,pre_m,14,tzinfo=UTC).isoformat(),
                "previsao_registrada_em":datetime(pre_y,pre_m,15,tzinfo=UTC).isoformat(),
                "vintage_publicada_em":datetime(pub_y,pub_m,3,tzinfo=UTC).isoformat(),
                "observacao_registrada_em":datetime(pub_y,pub_m,4,tzinfo=UTC).isoformat(),
                "previsto":110.,"observado":100.,"baseline":105.,
            })
        r=replay_river({"status":"AVALIACAO_DESCRITIVA_NAO_HOMOLOGADA",
            "agregacao_comparavel":True,"verdade":"PRIMEIRA_PUBLICACAO",
            "modo":"BACKTEST","avaliacoes":rows})
        self.assertEqual(r["avaliadas"],5)
        self.assertFalse(r["modelo_homologado"])

    @unittest.skipUnless(installed("duckdb"),"Instale .[ivo-query] em sandbox")
    def test_duckdb_real_parquet_sem_internet(self):
        import duckdb
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"test.parquet"
            con=duckdb.connect(database=":memory:")
            try:
                sql="""COPY (SELECT
                    'CONAB' AS fonte, 'PRODUCAO' AS variavel, 'SOJA' AS produto,
                    'MT' AS regiao, 't' AS unidade, '2026-01' AS competencia,
                    'MENSAL' AS calendario, '2026-01-01' AS referencia,
                    '2026-02-04' AS publicacao,
                    '2026-02-05T12:00:00+00:00' AS coleta,
                    100.0::DOUBLE AS valor, 'OBSERVADO' AS natureza,
                    'primeira' AS edicao
                    ) TO '""" + str(path).replace("'","''") + """' (FORMAT PARQUET)"""
                con.execute(sql)
            finally:con.close()
            r=carregar_asof_parquet(
                diretorio=tmp,arquivo="test.parquet",
                fonte="CONAB",variavel="PRODUCAO",produto="SOJA",
                regiao="MT",unidade="t",
                corte_publicacao=date(2026,2,10),
                corte_coleta=datetime(2026,2,10,tzinfo=UTC),
                acesso_autorizado=True)
            self.assertEqual(r["linhas_asof"],1)
            self.assertEqual(r["observacoes"][0].valor,100.)


if __name__=="__main__":
    unittest.main()
