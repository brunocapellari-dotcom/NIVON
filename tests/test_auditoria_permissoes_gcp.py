"""NIVON: testes offline de pré-voo consultivo, sem operações cloud mutáveis."""
import unittest
from types import SimpleNamespace
from scripts.auditar_permissoes_gcp import auditar, ErroPreflight


class NotFound(Exception): pass
class Forbidden(Exception): pass


class Bucket:
    name="nivon-data-raw-2026"
    location="southamerica-east1"
    def __init__(self,perms=None,denied=False):
        self.perms=perms or []
        self.denied=denied
        self.consultas=0
    def test_iam_permissions(self,asked,client=None,timeout=None):
        self.consultas+=1
        assert tuple(asked)==("storage.objects.get",
                               "storage.objects.create","storage.objects.list")
        if self.denied: raise Forbidden()
        return self.perms


class GCS:
    def __init__(self,perms=None,denied=False):
        self.bucket=Bucket(perms,denied)
    def get_bucket(self,name):
        assert name=="nivon-data-raw-2026"
        return self.bucket


class BQ:
    def __init__(self):
        self.readonly_calls=[]
        self.tabelas={}
    def get_dataset(self,ref):
        self.readonly_calls.append("dataset")
        assert ref=="nivon-data.nivon_raw"
        return SimpleNamespace(project="nivon-data",
                               dataset_id="nivon_raw",location="southamerica-east1")
    def get_table(self,ref):
        self.readonly_calls.append("table")
        if ref not in self.tabelas: raise NotFound()
        return self.tabelas[ref]


class PreflightPermissionsTest(unittest.TestCase):
    def test_permission_assessment_is_advisory(self):
        gcs=GCS(["storage.objects.get","storage.objects.create"])
        bq=BQ()
        r=auditar(projeto="nivon-data",dataset="nivon_raw",
                  bucket="nivon-data-raw-2026",bq=bq,storage=gcs,
                  not_found=NotFound,forbidden=Forbidden)
        self.assertTrue(r["gcs_iam"]["objeto_criacao_indicado"])
        self.assertFalse(r["acesso_workflow_escrita_comprovado"])
        self.assertFalse(r["upload_real_confirmado"])
        self.assertFalse(r["bigquery_write_confirmado"])
        self.assertEqual(r["escritas"],0)
        self.assertEqual(r["jobs_bigquery"],0)
        self.assertEqual(r["nivon_observacoes"],"AUSENTE")

    def test_denied_permissions_and_bad_partition(self):
        gcs=GCS(denied=True)
        bq=BQ()
        bq.tabelas["nivon-data.nivon_raw.agro_publicacoes_staging"]=SimpleNamespace(
            time_partitioning=SimpleNamespace(field="incorrect"))
        r=auditar(projeto="nivon-data",dataset="nivon_raw",
                  bucket="nivon-data-raw-2026",bq=bq,storage=gcs,
                  not_found=NotFound,forbidden=Forbidden)
        self.assertEqual(r["gcs_iam"]["estado"],"SEM_ACESSO_PARA_TESTE")
        self.assertEqual(r["agro_publicacoes_staging"],"PARTICAO_DIVERGENTE")

    def test_identifiers_fail_before_network(self):
        gcs=GCS()
        bq=BQ()
        with self.assertRaises(ErroPreflight):
            auditar(projeto="nivon-data",dataset="x;DROP TABLE",
                    bucket="nivon-data-raw-2026",bq=bq,storage=gcs,
                    not_found=NotFound,forbidden=Forbidden)
        self.assertEqual(bq.readonly_calls,[])
        self.assertEqual(gcs.bucket.consultas,0)


if __name__=="__main__":
    unittest.main()
