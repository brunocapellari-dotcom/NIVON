"""E2E SIADE view real existente, mocks somente do transporte Google Cloud."""
from __future__ import annotations
from datetime import date,datetime,timezone
from decimal import Decimal
import subprocess
import sys
import unittest

from nivon.ferrovia_painel_bq import consultar_ferrovia, plano_ferrovia
from nivon.ponte_painel_fontes import analisar_fontes
from nivon.transporte_multimodal import ErroTransporte
from nivon.painel_operacional import ErroMotor

AS_OF="2026-10-23T13:30:00Z"
CONFIG={"projeto":"nivon-data","dataset":"nivon_raw",
        "competencia":"2026-08","uf_origem":"MT"}


def linha(polo="MT_RONDONOPOLIS_FERRO",mercadoria="Soja",
          tu="17000.2",fonte="ANTT_SIADE_ORIGEM_DESTINO",**kw):
    d={
        "competencia":"2026-08","data_referencia":date(2026,8,1),
        "polo_id":polo,"ferrovia":"RUMO","estacao_origem":"Rondonopolis",
        "uf_origem":"MT","mercadoria_antt":mercadoria,
        "produto_normalizado":"SOJA_EM_GRAO",
        "estacao_destino":"Santos","uf_destino":"SP",
        "toneladas_uteis":Decimal(tu),"linhas_fonte":2,
        "arquivos_sha256":["a"*64],
        "data_coleta":datetime(2026,10,23,11,0,tzinfo=timezone.utc),
        "fonte":fonte,"abrangencia":"FERROVIAS_FEDERAIS_CONCEDIDAS",
        "match_geografico":"ESTACAO_NOME_EXATO_NAO_TERMINAL",
        "transbordo_confirmado":False,
    }
    return d|kw


class Param:
    def __init__(self,name,kind,val):
        self.name=name;self.kind=kind;self.value=val


class Config:
    def __init__(self,**kw):self.params=kw


class SDK:
    ScalarQueryParameter=Param
    QueryJobConfig=Config


class Job:
    def __init__(self,rows):self.rows=rows
    def result(self,timeout):assert timeout==90;return self.rows


class Client:
    def __init__(self,rows,view=True):
        self.rows=rows;self.view=view;self.calls=[];self.sql=None;self.config=None
    def get_dataset(self,ref):
        self.calls.append(("dataset",ref));return object()
    def get_table(self,ref):
        self.calls.append(("table",ref))
        return type("Table",(),{"table_type":"VIEW" if self.view else "TABLE"})()
    def query(self,sql,job_config):
        self.calls.append(("query",sql));self.sql=sql;self.config=job_config
        return Job(self.rows)


class FerroviaPainelBQTests(unittest.TestCase):
    def test_plano_offline_usa_view_existente_sem_credencial(self):
        r=consultar_ferrovia(**CONFIG,as_of=AS_OF)
        self.assertEqual(r["estado"],"PLANO_SEM_REDE")
        self.assertFalse(r["executado"])
        self.assertIn("vw_nivon_corredores_ferrovia_mensal",r["view"])
        self.assertFalse(r["somar_com_rodovia_permitido"])
        self.assertFalse(r["historico_pit_reconstruido"])

    def test_leitura_agregada_no_mes_mesma_fonte_e_hash(self):
        rows=[linha(),linha(mercadoria="Grãos - Milho",tu="3000.1",
             produto_normalizado="MILHO_EM_GRAO"),
             linha(polo="MT_ITIQUIRA_FERRO",mercadoria="Soja",tu="1200.5",
                   estacao_origem="Itiquira")]
        cli=Client(rows)
        r=consultar_ferrovia(**CONFIG,as_of=AS_OF,executar=True,cliente=cli,sdk=SDK)
        self.assertEqual(r["estado"],"REVISAO_ATUAL_CONSULTADA_NAO_HOMOLOGADA")
        self.assertEqual(r["linhas_view"],3)
        self.assertEqual(r["linhas_fonte"],6)
        self.assertEqual(r["polos_ferroviarios"][0]["toneladas_ferroviarias"],"20000.3")
        self.assertEqual(r["polos_ferroviarios"][1]["toneladas_ferroviarias"],"1200.5")
        self.assertEqual(len(r["polos_ferroviarios"][0]["mercadorias"]),2)
        self.assertEqual(r["arquivos_sha256"],["a"*64])
        self.assertFalse(r["historico_pit_reconstruido"])
        self.assertFalse(r["transbordo_confirmado"])
        self.assertIn("AND data_coleta <= @as_of",cli.sql)
        self.assertIn("data_referencia = @inicio",cli.sql)
        self.assertLess(cli.sql.index("competencia = @competencia"),
                        cli.sql.index("LIMIT @limite"))
        self.assertEqual(cli.config.params["maximum_bytes_billed"],50_000_000)
        vals={x.name:x.value for x in cli.config.params["query_parameters"]}
        self.assertEqual(vals["competencia"],"2026-08")
        self.assertEqual(vals["limite"],1001)

    def test_intermodal_com_mdf_e_nao_soma_modalidades(self):
        cli=Client([linha()])
        r=analisar_fontes(
            {"ferrovia_bigquery":CONFIG,
             "corredores":{
                 "estado":"RECORTE_IMPORTADO_NAO_HOMOLOGADO",
                 "recorte":"MT_SINTETICO","competencia":"2026-08",
                 "resumo_polos":[{"polo":{"id":"MT_RONDONOPOLIS_FERRO",
                   "modal_destino":"FERROVIARIO"},
                   "sentido":"DESTINO","toneladas_no_recorte":"40000",
                   "principais_origens":[]}]
             }},
            as_of=AS_OF,executar_bigquery=True,
            cliente_ferrovia_bq=cli,sdk_ferrovia_bq=SDK)
        row=r["conciliacao_intermodal"]["dados"][0]
        self.assertEqual(row["toneladas_ferroviarias_estacao_origem"],"17000.2")
        self.assertEqual(row["toneladas_rodoviarias_destino_geografico"],"40000")
        self.assertFalse(row["soma_entre_modais_permitida"])
        self.assertFalse(row["transbordo_confirmado"])
        self.assertTrue(r["executou_bigquery"])
        self.assertFalse(r["fonte_ferrovia_bigquery"]["historico_pit_reconstruido"])

    def test_modo_simulado_painel_nao_abre_cloud(self):
        cli=Client([linha()])
        r=analisar_fontes({"ferrovia_bigquery":CONFIG},
            as_of=AS_OF,executar_bigquery=False,cliente_ferrovia_bq=cli)
        self.assertEqual(cli.calls,[])
        self.assertEqual(r["fonte_ferrovia_bigquery"]["estado"],"PLANO_SEM_REDE")
        self.assertIsNone(r["ferrovia"])
        self.assertFalse(r["executou_bigquery"])

    def test_sem_linhas_nao_e_volume_zero(self):
        r=consultar_ferrovia(**CONFIG,as_of=AS_OF,executar=True,
                             cliente=Client([]),sdk=SDK)
        self.assertEqual(r["estado"],"SEM_REGISTROS_NAO_SIGNIFICA_ZERO")
        self.assertEqual(r["polos_ferroviarios"],[])
        self.assertTrue(r["sem_registro_nao_equivale_a_zero"])

    def test_truncamento_ou_proveniencia_errada_bloqueia(self):
        for invalido in (
            [linha()]*1001,
            [linha(transbordo_confirmado=True)],
            [linha(fonte="PORTO_SECUNDARIO")],
            [linha(toneladas_uteis=Decimal("NaN"))],
            [linha(data_coleta=datetime(2026,10,24,tzinfo=timezone.utc))],
            [linha(arquivos_sha256=["hash_qualquer"])],
            [linha(competencia="2026-07")],
            [linha(linhas_fonte=0)],
        ):
            with self.subTest(caso=str(invalido[0])[:80]):
                with self.assertRaises(ErroTransporte):
                    consultar_ferrovia(**CONFIG,as_of=AS_OF,executar=True,
                                      cliente=Client(invalido),sdk=SDK)

    def test_view_ausente_e_parametros_invalidos_fail_closed(self):
        with self.assertRaises(ErroTransporte):
            consultar_ferrovia(**CONFIG,as_of=AS_OF,executar=True,
                               cliente=Client([linha()],view=False),sdk=SDK)
        for config in (
            {"projeto":"nivon-data;DROP"},
            {"dataset":"raw;SELECT"},
            {"competencia":"2027-01"},
            {"competencia":"2026-00"},
            {"uf_origem":"MT';--"},
            {"max_bytes_billed":100_000_000},
            {"limite":1001},
        ):
            with self.subTest(invalido=config),self.assertRaises(ErroTransporte):
                consultar_ferrovia(**(CONFIG|config),as_of=AS_OF)

    def test_multiplas_fontes_ferrovia_nao_podem_competir(self):
        with self.assertRaises(ErroMotor):
            analisar_fontes({"ferrovia_bigquery":CONFIG,
                            "ferrovia_staging":{"pasta":"stage","ano":2026,
                            "competencia":"2026-08"}},as_of=AS_OF)

    def test_cli_sem_rede_e_testada_pelo_executavel_real(self):
        result=subprocess.run([sys.executable,"-m","nivon.ferrovia_painel_bq",
                "--projeto","nivon-data","--dataset","nivon_raw",
                "--competencia","2026-08","--as-of",AS_OF],
            capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        doc=__import__("json").loads(result.stdout)
        self.assertEqual(doc["estado"],"PLANO_SEM_REDE")
        self.assertFalse(doc["executado"])


if __name__=="__main__":
    unittest.main()
