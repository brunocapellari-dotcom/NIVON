"""Stage agro ausente não torna o inventário GCP inútil para o portal read-only."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/nivon-go-live-readonly.yml"

class TestGoLiveReadonlyStage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=WORKFLOW.read_text(encoding="utf-8")

    def test_tabela_opcional_nao_simula_carga_pronta(self):
        source=self.text.split("except NotFound:",1)[1].split("cols=",1)[0]
        self.assertIn("'AUSENTE_OPCIONAL_PARA_PORTAL'",source)
        self.assertIn("result['carga_agro_stage_pronta']=False",source)
        self.assertIn("result['portal_em_producao_comprovado']=False",source)
        self.assertIn("sys.exit(0)",source)

    def test_schema_existente_divergente_continua_bloqueado(self):
        self.assertIn("'SCHEMA_DIVERGENTE'",self.text)
        self.assertIn("if not valido:sys.exit(5)",self.text)

    def test_apenas_inventario_readonly_sem_criar_tabela(self):
        self.assertIn("bq.get_dataset(",self.text)
        self.assertIn("bq.get_table(",self.text)
        self.assertIn("storage.Client(project=project).get_bucket(",self.text)
        for operation in (".create_dataset(", ".create_table(", ".insert_rows",
                          "bq.query(", "gcloud services enable"):
            self.assertNotIn(operation,self.text)

if __name__=="__main__":
    unittest.main()
