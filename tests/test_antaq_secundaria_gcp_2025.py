"""Valida segregacao de fonte terceira, auditoria e idempotencia sem rede."""
import tempfile
import unittest
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nivon.antaq_secundaria_gcp_2025 import (
    preparar_lote,persistir,baixar_revisao_fixada,HF_COMMIT,FIELDS
)
from nivon.antaq_replica_hidrovia import ErroReplicaANTAQ

class FakeNotFound(Exception):pass

class SDK:
    class SchemaField:
        def __init__(self,name,field_type):
            self.name,self.field_type=name,field_type
    class Table:
        def __init__(self,ref,schema):
            self.schema=schema
            self.time_partitioning=None
    class TimePartitioningType:
        DAY="DAY"
    class TimePartitioning:
        def __init__(self,**kwargs):self.__dict__.update(kwargs)
    class QueryJobConfig:
        def __init__(self,**kwargs):self.__dict__.update(kwargs)
    class ScalarQueryParameter:
        def __init__(self,*args):self.args=args
    class LoadJobConfig:
        def __init__(self,**kwargs):self.__dict__.update(kwargs)
    class SourceFormat:
        NEWLINE_DELIMITED_JSON="NEWLINE_DELIMITED_JSON"
    class WriteDisposition:
        WRITE_APPEND="WRITE_APPEND"

class BQ:
    def __init__(self):
        self.table=None
        self.rows=[]
        self.loads=0
        self.sqls=[]
    def get_dataset(self,ref):
        return SimpleNamespace(location="southamerica-east1")
    def get_table(self,ref):
        if self.table is None:raise FakeNotFound()
        return self.table
    def create_table(self,tab):
        self.table=tab
        return tab
    def query(self,sql,job_config):
        self.sqls.append((sql,job_config.maximum_bytes_billed))
        result=SimpleNamespace(
            n=len(self.rows),
            tu=str(sum((Decimal(r["toneladas_trechos"]) for r in self.rows),Decimal(0))))
        return SimpleNamespace(result=lambda timeout:[result])
    def load_table_from_json(self,rows,ref,job_config,job_id):
        self.loads+=1
        self.rows.extend(rows)
        return SimpleNamespace(result=lambda timeout:None,errors=None)

def doc():
    return {
        "estado":"DERIVADO_TERCEIRO_2025_NAO_HOMOLOGADO","ano":2025,
        "nao_somar_hidrovias":True,
        "total_ton":92431869.759,
        "ton_com_classificacao_hidrovia":53250176.855,
    }

def recortes():
    return {"estado":"REPLICA_2025_TERCEIRO_NAO_HOMOLOGADA","ano":2025,
            "recortes_agro":[
            {"hidrovia":"Hidrovia do Madeira","navegacao":"Interior",
             "sentido":"Desembarcados","grupo_produto":"SOJA",
             "linhas":10,"toneladas":123.456},
            {"hidrovia":"Hidrovia do Tapajós","navegacao":"Interior",
             "sentido":"Desembarcados","grupo_produto":"MILHO",
             "linhas":12,"toneladas":444.555},
            {"hidrovia":"Hidrovia do Madeira","navegacao":"Longo Curso",
             "sentido":"Embarcados","grupo_produto":"SOJA",
             "linhas":8,"toneladas":999.0}]}

class Replica2025(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.h=Path(self.temp.name)/"hidrovia.parquet"
        self.c=Path(self.temp.name)/"carga.parquet"
        self.h.write_bytes(b"X"*200)
        self.c.write_bytes(b"Y"*300)
    def tearDown(self):self.temp.cleanup()

    def montar(self,**kw):
        with patch("nivon.antaq_secundaria_gcp_2025.resumo_parquets",
                   return_value=recortes()),\
             patch("nivon.antaq_secundaria_gcp_2025.resumo_agro",side_effect=lambda x:x),\
             patch("nivon.antaq_secundaria_gcp_2025.soma_carga_unica_2025",
                   return_value=kw.get("carga_unica",doc())):
            return preparar_lote(self.h,self.c,collected_at=datetime.now(timezone.utc))

    def test_apenas_interior_nao_aditivo_e_proveniencia(self):
        rows,p=self.montar()
        self.assertEqual(len(rows),2)
        self.assertEqual(p["linhas_hidroviarias"],2)
        self.assertEqual(p["toneladas_trechos_nao_aditivas"],"568.011")
        self.assertEqual(p["hf_revision"],HF_COMMIT)
        self.assertEqual(p["toneladas_navegacao_interior_idcarga_unica"],"92431869.759")
        self.assertTrue(all(x["dados_oficiais_antaq"] is False
                            and x["aditividade_entre_rios"] is False
                            and x["transbordo_confirmado"] is False for x in rows))
        self.assertTrue(all(set(x)==set(FIELDS) for x in rows))

    def test_valores_unicos_fora_da_prova_bloqueiam(self):
        x=doc();x["total_ton"]=999999
        with self.assertRaisesRegex(ErroReplicaANTAQ,"divergiu"):
            self.montar(carga_unica=x)

    def test_sem_timezone_bloqueia(self):
        with self.assertRaisesRegex(ErroReplicaANTAQ,"timezone"):
            preparar_lote(self.h,self.c,collected_at=datetime(2026,10,25))

    def test_idempotencia_no_bq_apartado(self):
        rows,p=self.montar()
        cli=BQ()
        a=persistir(rows,p,permitir_criar_tabela=True,
                    cliente=cli,sdk=SDK,not_found=FakeNotFound)
        b=persistir(rows,p,cliente=cli,sdk=SDK,not_found=FakeNotFound)
        self.assertEqual(a["estado"],"ANTAQ_REPLICA_SECUNDARIA_2025_BQ_CONCILIADA")
        self.assertEqual(b["bq_estado"],"JA_ARQUIVADO_IDEMPOTENTE")
        self.assertEqual(cli.loads,1)
        self.assertIn("terceiro",a["bq_tabela"])
        self.assertFalse(a["disponivel_na_camada_oficial"])
        self.assertTrue(all(s.startswith("SELECT ") and cap==60000000 for s,cap in cli.sqls))

    def test_cache_hf_link_simbolico_vira_copia_regular(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)
            blob=base/"objeto-fonte.parquet"
            blob.write_bytes(b"X"*2048)
            link=base/"cache.parquet"
            link.symlink_to(blob)
            destino=base/"staging"
            destino.mkdir()
            chamadas=[]
            def downloader(**kwargs):
                chamadas.append(kwargs)
                return str(link)
            with patch.dict("sys.modules",{
                "huggingface_hub":SimpleNamespace(hf_hub_download=downloader)
            }):
                paths=baixar_revisao_fixada(destino)
            self.assertEqual(len(chamadas),2)
            self.assertTrue(all(x["revision"]==HF_COMMIT for x in chamadas))
            for p in paths.values():
                self.assertTrue(Path(p).is_file())
                self.assertFalse(Path(p).is_symlink())
                self.assertNotEqual(Path(p),blob)
                self.assertEqual(Path(p).read_bytes(),b"X"*2048)

    def test_staging_symlink_bloqueia_antes_do_download(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)
            local=base/"real"
            local.mkdir()
            link=base/"alias"
            link.symlink_to(local,target_is_directory=True)
            with self.assertRaisesRegex(ErroReplicaANTAQ,"staging seguro ausente"):
                baixar_revisao_fixada(link)

    def test_nao_cria_tabela_sem_aprovacao_independente(self):
        rows,plano=self.montar()
        client=BQ()
        with self.assertRaisesRegex(ErroReplicaANTAQ,"bootstrap exige aprovacao"):
            persistir(rows,plano,cliente=client,sdk=SDK,not_found=FakeNotFound)
        self.assertEqual(client.loads,0)
        self.assertIsNone(client.table)

    def test_nunca_gravar_com_tag_oficial(self):
        rows,p=self.montar()
        rows[0]["dados_oficiais_antaq"]=True
        cli=BQ()
        with self.assertRaises(ErroReplicaANTAQ):
            persistir(rows,p,cliente=cli,sdk=SDK,not_found=FakeNotFound)
        self.assertEqual(cli.loads,0)

    def test_snapshot_parcial_bloqueia_reimportacao(self):
        rows,p=self.montar()
        cli=BQ()
        cli.table=SDK.Table("fake",[SDK.SchemaField(k,v) for k,v in FIELDS.items()])
        cli.table.time_partitioning=SDK.TimePartitioning(field="data_referencia")
        cli.rows=[rows[0]]
        with self.assertRaisesRegex(ErroReplicaANTAQ,"parcial"):
            persistir(rows,p,cliente=cli,sdk=SDK,not_found=FakeNotFound)
        self.assertEqual(cli.loads,0)

if __name__=="__main__":unittest.main()
