"""Testes para a carga OFICIAL top16 RGI, sem PDF externo e sem GCP pago."""
import unittest
from unittest.mock import patch
from datetime import datetime,timezone
from types import SimpleNamespace
from nivon.antt_rodovia_rgi_gcp import (
    preparar_documento,carregar,sql_view_atual,ErroRGIGCP,FIELDS
)

PDF=b"%PDF-1.5\n"+b"X"*120

def fixture():
    linhas=[]
    for i in range(16):
        linhas.append({
            "ano":2025, "origem_uf":"MT", "origem_rgi":"Rondonopolis"+str(i),
            "destino_uf":"SP","destino_rgi":"Santos"+str(i),
            "toneladas":100000+i,"participacao_pct":"1.00",
            "granularidade":"RGI","escopo":"TOP_16_FLUXOS_GERAIS_ANUAIS",
            "produto":None,"ncm":None,
        })
    return linhas

class FakeBQSDK:
    class NotFound(Exception): pass
    class SchemaField:
        def __init__(self,name,field_type):
            self.name,self.field_type=name,field_type
    class Table:
        def __init__(self,ref,schema):
            self.schema=schema
            self.time_partitioning=None
            self.clustering_fields=None
    class TimePartitioningType:
        DAY="DAY"
    class TimePartitioning:
        def __init__(self,**kw): self.__dict__.update(kw)
    class QueryJobConfig:
        def __init__(self,**kw): self.__dict__.update(kw)
    class ScalarQueryParameter:
        def __init__(self,*args): self.args=args
    class LoadJobConfig:
        def __init__(self,**kw): self.__dict__.update(kw)
    class SourceFormat:
        NEWLINE_DELIMITED_JSON="NEWLINE_DELIMITED_JSON"
    class WriteDisposition:
        WRITE_APPEND="WRITE_APPEND"

class FakeClient:
    def __init__(self):
        self.table=None
        self.rows=[]
        self.loads=0
        self.queries=[]
    def get_dataset(self,ref): return True
    def get_table(self,ref):
        if self.table is None: raise FakeBQSDK.NotFound()
        return self.table
    def create_table(self,table):
        self.table=table
        return table
    def query(self,sql,job_config):
        self.queries.append((sql,job_config))
        if sql.startswith("CREATE"):
            return SimpleNamespace(result=lambda timeout:[])
        result=SimpleNamespace(n=len(self.rows),tu=sum(r["toneladas"] for r in self.rows))
        return SimpleNamespace(result=lambda timeout:[result])
    def load_table_from_json(self,rows,ref,job_config,job_id):
        self.loads+=1
        self.rows.extend(rows)
        return SimpleNamespace(result=lambda timeout:None,errors=None)

class RGI2025GCP(unittest.TestCase):
    def test_preparar_16_registros_escopo_e_soma(self):
        with patch("nivon.antt_rodovia_rgi_gcp.texto_pdf",return_value="synthetic"),\
             patch("nivon.antt_rodovia_rgi_gcp.extrair_tabela_12",return_value=fixture()):
            r,m=preparar_documento(PDF,data_coleta=datetime(2026,10,23,tzinfo=timezone.utc))
        self.assertEqual(len(r),16)
        self.assertEqual(m["toneladas_top16"],str(sum(x["toneladas"] for x in fixture())))
        self.assertTrue(all(x["data_publicacao"] is None and x["granularidade"]=="RGI" for x in r))
        self.assertFalse(m["produto_identificado"])

    def test_rejeitar_produto_inventado_e_chaves_duplicadas(self):
        for alteração in ("produto","duplicado"):
            rows=fixture()
            if alteração=="produto":rows[0]["ncm"]="1201"
            else: rows[1]=rows[0].copy()
            with patch("nivon.antt_rodovia_rgi_gcp.texto_pdf",return_value="test"),\
                 patch("nivon.antt_rodovia_rgi_gcp.extrair_tabela_12",return_value=rows):
                with self.assertRaises(ErroRGIGCP):
                    preparar_documento(PDF,data_coleta=datetime.now(timezone.utc))

    def test_rejeitar_pdf_invalido_e_data_sem_fuso(self):
        for pdf,dt in ((b"<html>Error</html>",datetime.now(timezone.utc)),
                       (PDF,datetime(2026,10,23))):
            with self.assertRaises(ErroRGIGCP):
                preparar_documento(pdf,data_coleta=dt)

    def test_grava_concilia_e_idempotente(self):
        bq=FakeClient()
        storage=[]
        def gravar(pdf,plano):
            storage.append(plano["sha256"])
            return {"estado":"ARQUIVADO","sha256":plano["sha256"],"uri":"gs://prova/teste.pdf"}
        with patch("nivon.antt_rodovia_rgi_gcp.texto_pdf",return_value="test"),\
             patch("nivon.antt_rodovia_rgi_gcp.extrair_tabela_12",return_value=fixture()):
            a=carregar(PDF,data_coleta=datetime.now(timezone.utc),cliente_bq=bq,
                      sdk=FakeBQSDK,arquivador=gravar)
            b=carregar(PDF,data_coleta=datetime.now(timezone.utc),cliente_bq=bq,
                      sdk=FakeBQSDK,arquivador=gravar)
        self.assertEqual(bq.loads,1)
        self.assertEqual(a["estado"],"ANTT_RGI_TOP16_2025_CONCILIADO")
        self.assertEqual(b["bq_estado"],"SEM_MUDANCA")
        self.assertEqual(len(storage),2)
        self.assertTrue(all(x["maximum_bytes_billed"]<=60_000_000 for _,x in bq.queries))
        self.assertFalse(a["somar_com_ferrovia_ou_hidrovia"])

    def test_preexistente_parcial_bloqueia(self):
        bq=FakeClient()
        bq.table=FakeBQSDK.Table("ref",[FakeBQSDK.SchemaField(k,v) for k,v in FIELDS.items()])
        bq.table.time_partitioning=FakeBQSDK.TimePartitioning(field="data_referencia")
        bq.rows=fixture()[:2]
        with patch("nivon.antt_rodovia_rgi_gcp.texto_pdf",return_value="test"),\
             patch("nivon.antt_rodovia_rgi_gcp.extrair_tabela_12",return_value=fixture()):
            with self.assertRaisesRegex(ErroRGIGCP,"parcial"):
                carregar(PDF,data_coleta=datetime.now(timezone.utc),cliente_bq=bq,
                        sdk=FakeBQSDK,arquivador=lambda *a,**k:None)
        self.assertEqual(bq.loads,0)

    def test_view_deduplica_por_identidade_rgi(self):
        s=sql_view_atual()
        self.assertIn("ROW_NUMBER()",s)
        self.assertIn("PARTITION BY ano,origem_uf,origem_rgi,destino_uf,destino_rgi",s)

if __name__=="__main__":
    unittest.main()
