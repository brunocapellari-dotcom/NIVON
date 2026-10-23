"""Readback marítimo RO: programações, PortWatch, revisões e gates."""
from __future__ import annotations

from datetime import date,datetime,timezone
import json
import tempfile
from pathlib import Path
import subprocess
import sys
import unittest

from nivon.maritimo_painel_bigquery import (
    ErroPainelMaritimo, consultar_maritimo, planejar_maritimo)
from nivon.painel_operacional import ErroMotor
from nivon.ponte_painel_fontes import analisar_fontes

AS_OF="2026-10-23T18:50:00Z"
CFG={"projeto":"nivon-data","dataset":"nivon_raw","inicio":"2026-10-01",
     "fim":"2026-10-31"}
NOW=datetime(2026,10,23,17,30,tzinfo=timezone.utc)
PUB=datetime(2026,10,21,12,tzinfo=timezone.utc)


class Param:
    def __init__(self,name,kind,value):
        self.name=name;self.kind=kind;self.value=value


class Config:
    def __init__(self,**kwargs):self.kwargs=kwargs


class SDK:
    ScalarQueryParameter=Param
    QueryJobConfig=Config


class Job:
    def __init__(self,rows):self.rows=rows
    def result(self,timeout):
        assert timeout==90
        return self.rows


class Client:
    def __init__(self,rows,part="data_referencia",table_type="TABLE"):
        self.rows=rows;self.part=part;self.table_type=table_type;self.calls=[]
        self.sql=None;self.cfg=None
    def get_dataset(self,key):
        self.calls.append("dataset")
        return object()
    def get_table(self,key):
        self.calls.append("table")
        return type("Table",(),{"table_type":self.table_type,
            "time_partitioning":type("Part",(),{"field":self.part})()})()
    def query(self,sql,job_config):
        self.calls.append("query")
        self.sql=sql;self.cfg=job_config
        return Job(self.rows)


def lineup(**over):
    r={
        "fonte":"imbituba","escala_id":"PROGRAMACAO_001",
        "revisao_sha256":"a"*64,
        "data_referencia":date(2026,10,23),"competencia":"2026-10",
        "data_publicacao":PUB,"data_coleta":NOW,
        "natureza":"INFORMADO_PELA_FONTE",
        "situacao":"ATRACADO_INFORMADO","publicavel":True,
        "payload_json":json.dumps({"porto":"IMBITUBA","natureza":"INFORMADO_PELA_FONTE"}),
    }
    return r|over


def passage(**over):
    r={
        "fonte":"FMI_PORTWATCH","passagem":"panama",
        "revisao_sha256":"b"*64,"data_referencia":date(2026,10,22),
        "data_coleta":NOW,"transitos_ais":2,
        "volume_transito_estimado_t":1100.25,
        "payload_json":json.dumps({
            "volume_realizado_t":None,"natureza_volume_estimado":"ESTIMADO_MODELO_FMI"
        })
    }
    return r|over


class MaritimoPainelBQTests(unittest.TestCase):
    def test_plano_sem_credenciais_e_parametros(self):
        p=consultar_maritimo(**CFG,fonte="imbituba",as_of=AS_OF)
        self.assertEqual(p["estado"],"PLANO_SEM_REDE")
        self.assertFalse(p["executado"])
        cli=Client([lineup()])
        x=consultar_maritimo(**CFG,fonte="imbituba",as_of=AS_OF,
                             executar=True,client=cli,sdk=SDK,limite=10)
        self.assertEqual(x["revisoes_visiveis"],1)
        self.assertIn("maritimo_escalas_revisoes",cli.sql)
        self.assertIn("data_referencia BETWEEN @inicio AND @fim",cli.sql)
        self.assertIn("data_coleta <= @as_of",cli.sql)
        self.assertEqual(cli.cfg.kwargs["maximum_bytes_billed"],50_000_000)
        self.assertEqual({p.name:p.value for p in cli.cfg.kwargs["query_parameters"]}["limite"],11)

    def test_revisoes_de_programacao_nao_confirmam_navios(self):
        r=consultar_maritimo(**CFG,fonte="imbituba",as_of=AS_OF,executar=True,
            client=Client([lineup(),lineup(revisao_sha256="c"*64)]),sdk=SDK)
        self.assertEqual(r["revisoes_visiveis"],2)
        self.assertEqual(r["ids_programacao_distintos"],1)
        self.assertEqual(r["hashes_revisoes_distintos"],2)
        self.assertIsNone(r["navios_operados_confirmados"])
        self.assertIsNone(r["toneladas_realizadas"])
        self.assertIsNone(r["navios_em_fila_ais"])
        self.assertFalse(r["vinculo_duv_confirmado"])
        self.assertFalse(r["publicavel"])

    def test_cdp_santarem_nao_considerar_dados_validados(self):
        row=lineup(fonte="santarem_cdp",situacao="PROGRAMADO",publicavel=False)
        x=consultar_maritimo(**CFG,fonte="santarem_cdp",as_of=AS_OF,
                             executar=True,client=Client([row]),sdk=SDK)
        self.assertEqual(x["revisoes_bloqueadas_fonte"],1)
        self.assertFalse(x["publicavel"])

    def test_revisoes_fora_do_recorte_e_corrompidas_bloqueadas(self):
        casos=[
            lineup(fonte="suape"),lineup(revisao_sha256="hash_ruim"),
            lineup(data_referencia=date(2026,9,30)),
            lineup(data_coleta=datetime(2026,10,24,tzinfo=timezone.utc)),
            lineup(data_publicacao=datetime(2026,10,24,tzinfo=timezone.utc)),
            lineup(payload_json="[1,2]"),lineup(situacao=None),
            lineup(publicavel=None),
        ]
        for caso in casos:
            with self.subTest(caso=str(caso)[:60]),self.assertRaises(ErroPainelMaritimo):
                consultar_maritimo(**CFG,fonte="imbituba",as_of=AS_OF,executar=True,
                    client=Client([caso]),sdk=SDK)

    def test_teto_particao_vista_e_truncamento(self):
        for c in (Client([lineup()],part=None),Client([lineup()],table_type="VIEW"),
                  Client([lineup()]*2)):
            with self.subTest(c=c.calls),self.assertRaises(ErroPainelMaritimo):
                consultar_maritimo(**CFG,fonte="imbituba",as_of=AS_OF,
                    executar=True,client=c,sdk=SDK,limite=1)

    def test_portwatch_deduplica_revisoes_por_dia(self):
        old=passage(
            revisao_sha256="a"*64,
            data_coleta=datetime(2026,10,22,14,tzinfo=timezone.utc),
            volume_transito_estimado_t=5000)
        latest=passage()
        outro=passage(data_referencia=date(2026,10,21),transitos_ais=4,
                      volume_transito_estimado_t=200)
        x=consultar_maritimo(**CFG,passagem="panama",as_of=AS_OF,
            executar=True,client=Client([old,latest,outro]),sdk=SDK)
        self.assertEqual(x["revisoes_visiveis"],3)
        self.assertEqual(x["dias_distintos"],2)
        self.assertEqual(x["vintages_descartadas_para_soma"],1)
        self.assertEqual(x["volume_estimado_modelo_t"],"1300.25")
        self.assertEqual(x["transitos_ais_reportados"],6)
        self.assertIsNone(x["volume_movimentado_real"])
        self.assertIsNone(x["transitos_portuarios_confirmados"])

    def test_portwatch_payload_que_afirma_volume_real_e_bloqueado(self):
        bad=passage(payload_json=json.dumps({
            "natureza_volume_estimado":"ESTIMADO_MODELO_FMI","volume_realizado_t":100}))
        with self.assertRaises(ErroPainelMaritimo):
            consultar_maritimo(**CFG,passagem="panama",as_of=AS_OF,
                executar=True,client=Client([bad]),sdk=SDK)

    def test_empty_nao_equivale_a_zero_e_ausencia_de_fontes(self):
        a=consultar_maritimo(**CFG,fonte="imbituba",as_of=AS_OF,
            executar=True,client=Client([]),sdk=SDK)
        self.assertEqual(a["estado"],"SEM_REVISOES_NAO_EQUIVALE_A_ZERO")
        b=consultar_maritimo(**CFG,passagem="panama",as_of=AS_OF,
            executar=True,client=Client([]),sdk=SDK)
        self.assertIsNone(b["volume_estimado_modelo_t"])
        self.assertEqual(b["estado"],"SEM_DADOS_NAO_EQUIVALE_A_ZERO")

    def test_parametros_maliciosos_bloqueados(self):
        changes=[
            {"projeto":"nivon-data;--"},{"dataset":"raw;--"},
            {"inicio":"2025-01-01"},{"fim":"2027-01-01"},
            {"fonte":"santarem_cdp;drop"},{"fonte":None,"passagem":None},
            {"fonte":"imbituba","passagem":"panama"},
            {"limite":1001},{"max_bytes_billed":100_000_000},
            {"as_of":"2026-10-23"},
        ]
        for change in changes:
            kw=dict(CFG,as_of=AS_OF,fonte="imbituba")|change
            with self.subTest(kwargs=change),self.assertRaises(ValueError):
                planejar_maritimo(**kw)

    def test_painel_lote_com_dois_tipos_de_fontes(self):
        def mocked(**kwargs):
            if kwargs["executar"] is not True:
                return consultar_maritimo(**CFG,fonte=kwargs.get("fonte"),
                           passagem=kwargs.get("passagem"),as_of=AS_OF)
            cli=Client([lineup()] if kwargs["fonte"] else [passage()])
            return consultar_maritimo(**CFG,fonte=kwargs.get("fonte"),
                 passagem=kwargs.get("passagem"),as_of=AS_OF,
                 executar=True,client=cli,sdk=SDK,limite=kwargs["limite"])
        inp={"consultas_maritimas_bigquery":[
            dict(CFG,fonte="imbituba",limite=10),
            dict(CFG,passagem="panama",limite=10)]}
        out=analisar_fontes(inp,as_of=AS_OF,executar_bigquery=True,
                           leitor_maritimo_bq=mocked)
        self.assertEqual(len(out["fontes_maritimas_bigquery"]),2)
        self.assertTrue(out["executou_bigquery"])
        self.assertEqual(out["maritimo"],[])
        self.assertFalse(out["fontes_maritimas_bigquery"][0]["publicavel"])
        self.assertIsNone(out["fontes_maritimas_bigquery"][0]["navios_em_fila_ais"])
        with self.assertRaises(ErroMotor):
            analisar_fontes({"consultas_maritimas_bigquery":inp["consultas_maritimas_bigquery"]*2},
                            as_of=AS_OF)

    def test_painel_cli_em_dry_run_sem_cloud(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            entrada=Path(tmp)/"dados.json"
            entrada.write_text(json.dumps({"consultas_maritimas_bigquery":[
                dict(CFG,fonte="imbituba")]}),encoding="utf-8")
            p=subprocess.run([sys.executable,
                str(Path(__file__).resolve().parents[1]/"scripts"/"rodar_painel_operacional.py"),
                "--entrada",str(entrada),"--as-of",AS_OF],
                capture_output=True,text=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stderr+" "+p.stdout)
            doc=json.loads(p.stdout)
            self.assertEqual(doc["fontes_maritimas_bigquery"][0]["estado"],
                             "PLANO_SEM_REDE")
            self.assertFalse(doc["executou_bigquery"])


if __name__=="__main__":
    unittest.main()
