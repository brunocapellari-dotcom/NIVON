"""Tests GCP SQL/view as dry-run, without credentials or paid cloud writes."""
import unittest
from nivon.antt_bigquery import DestinoBQ
from nivon.corredores_bigquery import sql_view_corredores,nome_view,publicar_view
from nivon.transporte_multimodal import ErroTransporte


class MockQueryJobConfig:
    def __init__(self, **kwargs):
        self.settings=kwargs

class MockSDK:
    QueryJobConfig=MockQueryJobConfig

class MockJob:
    errors=None
    job_id="job_sintetico"
    def result(self,timeout):
        assert timeout==120

class MockClient:
    def __init__(self,view=True):
        self.view=view
        self.queried=[]
        self.datasets=[]
    def get_dataset(self,key):
        self.datasets.append(key)
        return object()
    def get_table(self,key):
        return type("Table",(),{"table_type":"VIEW" if self.view else "TABLE"})()
    def query(self,sql,job_config):
        self.queried.append((sql,job_config))
        return MockJob()


class TestViewCorredores(unittest.TestCase):
    def test_query_so_polos_nome_exato_e_vintage(self):
        d=DestinoBQ("nivon-local-demo","logistica")
        sql=sql_view_corredores(d)
        self.assertIn(d.view_completa,sql)
        self.assertIn(nome_view(d),sql)
        self.assertIn("MT_RONDONOPOLIS_FERRO",sql)
        self.assertIn("MT_ITIQUIRA_FERRO",sql)
        self.assertIn("MT_DOM_AQUINO_BR070",sql)
        self.assertIn("grãos - milho",sql)
        self.assertIn("SUM(toneladas_uteis)",sql)
        self.assertIn("ARRAY_AGG(DISTINCT arquivo_sha256",sql)
        self.assertIn("FALSE AS transbordo_confirmado",sql)
        self.assertIn("WHERE polo_id IS NOT NULL",sql)
        self.assertNotIn("TRANSBORDO_CONFIRMADO",sql)

    def test_dry_run_nao_invoca_cliente(self):
        d=DestinoBQ("nivon-local-demo","logistica")
        cliente=MockClient()
        x=publicar_view(d,cliente=cliente,sdk=MockSDK)
        self.assertEqual(x["estado"],"DRY_RUN_SEM_CONEXAO_GCP")
        self.assertEqual(cliente.queried,[])
        self.assertEqual(cliente.datasets,[])

    def test_live_exige_view_canonicamente_atual(self):
        d=DestinoBQ("nivon-local-demo","logistica")
        with self.assertRaises(ErroTransporte):
            publicar_view(d,habilitar_ddl=True,cliente=MockClient(view=False),sdk=MockSDK)
        client=MockClient()
        x=publicar_view(d,habilitar_ddl=True,cliente=client,sdk=MockSDK)
        self.assertEqual(x["estado"],"VIEW_CRIADA_NAO_HOMOLOGADA")
        self.assertEqual(len(client.queried),1)
        self.assertEqual(client.queried[0][1].settings["maximum_bytes_billed"],50_000_000)
        self.assertEqual(client.datasets,["nivon-local-demo.logistica"])

    def test_identificadores_maliciosos_rejeitados(self):
        for projeto,dataset in (
            ("P R O","data"),
            ("nivon-local-demo","dados; DROP TABLE z"),
        ):
            with self.subTest(projeto=projeto,dataset=dataset):
                with self.assertRaises(ErroTransporte):
                    DestinoBQ(projeto,dataset)

if __name__=="__main__":
    unittest.main()
