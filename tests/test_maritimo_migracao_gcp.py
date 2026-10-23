"""Contrato inicial BigQuery SQL, usando apenas dataset já existente."""
import runpy
import tempfile
import unittest
from pathlib import Path

fn=runpy.run_path(str(Path(__file__).resolve().parents[1]/
   "infra/google_cloud/gerar_migracao_maritima.py"))
gerar_sql=fn["gerar_sql"]
aplicar_sql=fn["aplicar_sql"]

class FakeBQ:
    def __init__(self):self.calls=[]
    def get_dataset(self,ref):
        self.calls.append(("dataset",ref))
    def query(self,sql):
        self.calls.append(("query",sql))
        return self
    def result(self,timeout=None):return self
    def get_table(self,ref):
        self.calls.append(("table",ref))

class MigracaoInicial(unittest.TestCase):
    def test_gera_dentro_do_projeto_existente_sem_ddl_publicado(self):
        rendered=gerar_sql(projeto="nivon-data",dataset="nivon_raw")
        self.assertIn("nivon-data.nivon_raw.maritimo_capturas",rendered)
        self.assertIn("nivon-data.nivon_raw.maritimo_estado_fontes_v",rendered)
        self.assertNotIn("NIVON_PROJECT_ID",rendered)
        self.assertEqual(rendered.count("CREATE TABLE IF NOT EXISTS"),4)

    def test_sem_autorizacao_ddl_nao_e_executado(self):
        fake=FakeBQ()
        with self.assertRaises(PermissionError):
            aplicar_sql("anything",projeto="nivon-data",
              dataset="nivon_raw",client=fake)
        self.assertEqual(fake.calls,[])

    def test_ddl_idempotente_somente_no_dataset_existente(self):
        fake=FakeBQ()
        ddl=gerar_sql(projeto="nivon-data",dataset="nivon_raw")
        output=aplicar_sql(ddl,projeto="nivon-data",dataset="nivon_raw",
                           autorizado=True,client=fake)
        self.assertTrue(output["executado"])
        self.assertEqual(fake.calls[0],("dataset","nivon-data.nivon_raw"))
        self.assertEqual(sum(k=="query" for k,_ in fake.calls),1)
        self.assertEqual(sum(k=="table" for k,_ in fake.calls),4)

    def test_rejeita_projeto_injetado(self):
        with self.assertRaises(ValueError):
            gerar_sql(projeto="nivon-data;DROP TABLE",dataset="nivon_raw")
        with self.assertRaises(ValueError):
            gerar_sql(projeto="nivon-data",dataset="../dev")

if __name__=="__main__":
    unittest.main()
