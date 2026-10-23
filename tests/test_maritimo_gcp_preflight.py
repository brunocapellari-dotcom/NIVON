"""Inventario read-only GCP sem criar recursos e sem autenticar na CI."""
import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path
import runpy

MODULE=runpy.run_path(str(Path(__file__).resolve().parents[1]/
                         "infra/google_cloud/preflight_maritimo.py"))
auditoria=MODULE["auditoria"]
executar_comando=MODULE["executar_comando"]

class InventarioCloud(unittest.TestCase):
    def test_inventario_nao_executa_nenhuma_mutacao(self):
        calls=[]
        def fake(args,**kwargs):
            calls.append(args)
            if "get-value" in args:
                return subprocess.CompletedProcess(args,0,"nivon-real-123\n","")
            if "services" in args:
                return subprocess.CompletedProcess(args,0,'[]',"")
            return subprocess.CompletedProcess(args,0,'{}',"")
        with patch.dict("os.environ",{"GOOGLE_CLOUD_PROJECT":""},clear=False):
            r=auditoria(regiao="southamerica-east1",bucket="bucket-exemplo-123",runner=fake)
        self.assertEqual(r["projeto"],"nivon-real-123")
        self.assertFalse(r["apto_para_implantacao"])
        self.assertEqual(len(calls),7)
        self.assertTrue(all("create" not in x and "delete" not in x for x in calls))

    def test_proibicao_de_mutacao_e_input(self):
        def fake(args,**kwargs):
            raise AssertionError("nao deveria ter chamado")
        with self.assertRaises(ValueError):
            executar_comando(["gcloud","projects","delete","abc"],runner=fake)
        with self.assertRaises(ValueError):
            auditoria(projeto="p;rm-rf",regiao="southamerica-east1",runner=fake)
        with self.assertRaises(ValueError):
            auditoria(projeto="nivon-real-123",regiao="../malicioso",runner=fake)

    def test_permissao_desconhecida_nao_vira_ausencia_confirmada(self):
        def fake(args,**kwargs):
            return subprocess.CompletedProcess(args,1,"","permission denied")
        r=auditoria(projeto="nivon-real-123",regiao="southamerica-east1",runner=fake)
        self.assertEqual(r["bigquery_dataset"]["estado"],"NAO_VERIFICADO")
        self.assertFalse(r["apto_para_implantacao"])

if __name__=="__main__":
    unittest.main()
