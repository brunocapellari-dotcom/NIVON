"""Preflight Google Cloud read-only, permissões, schema e residência com clientes fake."""
import unittest
from dataclasses import dataclass
from nivon.preflight_google_cloud import (
    EXPECTED_SCHEMA, ErroPreflightCloud, verificar_configuracao, verificar_recursos,
)

@dataclass
class IAM:
    uniform_bucket_level_access_enabled: bool=True
    public_access_prevention: str="enforced"

@dataclass
class Bucket:
    name: str="nivon-raw-privado"
    location: str="US"
    iam_configuration: IAM | None=None
    def __post_init__(self):
        if self.iam_configuration is None:
            self.iam_configuration=IAM()

@dataclass
class Dataset:
    location: str="US"

@dataclass
class Column:
    name: str
    field_type: str
    mode: str="NULLABLE"

@dataclass
class Table:
    project: str="nivon-data"
    dataset_id: str="nivon_stage"
    table_type: str="TABLE"
    schema: list | None=None
    time_partitioning: object | None=None
    def __post_init__(self):
        if self.schema is None:
            self.schema=[Column(k,t) for k,t in EXPECTED_SCHEMA.items()]

class StorageFake:
    project="nivon-data"
    def __init__(self,bucket=None):
        self.obj=bucket or Bucket()
        self.chamadas=[]
    def get_bucket(self,n):
        self.chamadas.append(("get_bucket",n))
        return self.obj

class BigQueryFake:
    project="nivon-data"
    def __init__(self,dataset=None,table=None):
        self.ds=dataset or Dataset()
        self.tb=table or Table()
        self.chamadas=[]
    def get_dataset(self,n):
        self.chamadas.append(("get_dataset",n))
        return self.ds
    def get_table(self,n):
        self.chamadas.append(("get_table",n))
        return self.tb

CFG={"projeto":"nivon-data","dataset":"nivon_stage","bucket":"nivon-raw-privado"}

class TestPreflightCloud(unittest.TestCase):
    def executar(self,storage=None,bigquery=None):
        return verificar_recursos(**CFG,cliente_storage=storage or StorageFake(),
                                 cliente_bigquery=bigquery or BigQueryFake())

    def test_recursos_validos_sem_escrita(self):
        gcs=StorageFake()
        bq=BigQueryFake()
        res=self.executar(storage=gcs,bigquery=bq)
        self.assertEqual(res["status"],"PRONTO_PARA_SMOKE_CONTROLADO")
        self.assertFalse(res["executou_upload"])
        self.assertFalse(res["executou_query"])
        self.assertFalse(res["go_live_confirmado"])
        self.assertFalse(res["verificou_limite_orcamentario"])
        self.assertFalse(res["particionamento_confirmado"])
        self.assertEqual(len(gcs.chamadas),1)
        self.assertEqual(len(bq.chamadas),2)

    def test_bloqueia_publico_e_heranca_indeterminada(self):
        for policy in ("inherited", "", None):
            with self.subTest(policy=policy), self.assertRaises(ErroPreflightCloud):
                self.executar(storage=StorageFake(Bucket(
                    iam_configuration=IAM(public_access_prevention=policy))))
        with self.assertRaises(ErroPreflightCloud):
            self.executar(storage=StorageFake(Bucket(
                iam_configuration=IAM(uniform_bucket_level_access_enabled=False))))

    def test_bloqueia_localizacao_e_tabela_ou_view(self):
        with self.assertRaises(ErroPreflightCloud):
            self.executar(storage=StorageFake(Bucket(location="SOUTHAMERICA-EAST1")))
        with self.assertRaises(ErroPreflightCloud):
            self.executar(bigquery=BigQueryFake(table=Table(table_type="VIEW")))
        with self.assertRaises(ErroPreflightCloud):
            self.executar(bigquery=BigQueryFake(table=Table(project="outro-projeto")))
        with self.assertRaises(ErroPreflightCloud):
            self.executar(bigquery=BigQueryFake(dataset=Dataset(location=None)))

    def test_bloqueia_schema_incompleto_ou_coluna_errada(self):
        fields=[Column(k,t) for k,t in EXPECTED_SCHEMA.items()]
        with self.assertRaises(ErroPreflightCloud):
            self.executar(bigquery=BigQueryFake(table=Table(schema=fields[1:])))
        errado=[Column(k,("STRING" if t=="JSON" else t)) for k,t in EXPECTED_SCHEMA.items()]
        with self.assertRaises(ErroPreflightCloud):
            self.executar(bigquery=BigQueryFake(table=Table(schema=errado)))
        duplicate=fields+[fields[0]]
        with self.assertRaises(ErroPreflightCloud):
            self.executar(bigquery=BigQueryFake(table=Table(schema=duplicate)))

    def test_cli_bloqueia_coleta_antes_de_abrir_http(self):
        from unittest.mock import patch
        from scripts import coletar_google_cloud, coletar_sgs_google_cloud
        env={
            "NIVON_GCP_OPERACIONAL_APROVADO":"true",
            "NIVON_GCP_DIREITOS_DADOS":"true",
            "NIVON_ZERO_COST_BQ_APPROVED":"true",
            "NIVON_FONTE_BCB_SGS_TAXA_SELIC_DIARIA_ATIVA":"true",
            "NIVON_GCP_RIGHTS_EVIDENCE":"Coleta pública verificada",
            "NIVON_BQ_PROJECT":"nivon-data",
            "NIVON_BQ_DATASET":"nivon_stage",
            "NIVON_GCS_BUCKET":"nivon-raw-privado",
        }
        with patch.dict("os.environ",env,clear=True):
            with patch("nivon.preflight_google_cloud.verificar_recursos",
                       side_effect=ErroPreflightCloud("IAM bloqueado")) as cloud:
                with self.assertRaisesRegex(ErroPreflightCloud,"IAM bloqueado"):
                    coletar_google_cloud.main(["--fonte","BCB_PTAX","--executar"])
                with self.assertRaisesRegex(ErroPreflightCloud,"IAM bloqueado"):
                    coletar_sgs_google_cloud.main(["--executar"])
                self.assertEqual(cloud.call_count,2)

    def test_validacao_identificadores_e_clientes(self):
        for cfg in [
            dict(CFG,bucket="../outro"),
            dict(CFG,projeto="outro_projeto"),
            dict(CFG,dataset="invalido-nome"),
        ]:
            with self.assertRaises(ErroPreflightCloud):
                verificar_configuracao(**cfg)
        bq=BigQueryFake()
        bq.project="diferente"
        with self.assertRaises(ErroPreflightCloud):
            self.executar(bigquery=bq)

if __name__=="__main__":
    unittest.main()
