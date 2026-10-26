"""Testa o contrato real do inventário, sem prender arquitetura ao YAML."""
import unittest
from pathlib import Path

from nivon.prontidao_golive_piloto import consolidar

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github"/"workflows"/"nivon-go-live-readonly.yml"
SOURCE=ROOT/"src"/"nivon"/"prontidao_golive_piloto.py"
SCRIPT=ROOT/"scripts"/"verificar_golive_gcp_readonly.py"


def resultado(stage="AUSENTE",view="VIEW"):
    return consolidar(
        regiao_dataset="southamerica-east1",
        regiao_bucket="southamerica-east1",
        acesso_publico="enforced",
        tipo_view=view,
        stage=stage,
    )


class TestGoLiveReadonlyStage(unittest.TestCase):
    def test_tabela_opcional_nao_simula_carga_pronta(self):
        r=resultado(stage="AUSENTE")
        self.assertEqual(r["stage_agro"],"AUSENTE")
        self.assertEqual(r["estado"],"PILOTO_DADOS_READONLY_PRONTO")
        self.assertFalse(r["stage_agro_bloqueia_piloto_ferrovia"])
        self.assertFalse(r["libera_deploy"])
        self.assertFalse(r["libera_whatsapp"])
        self.assertEqual(r["terminal_cloud_run_implantado"],"NAO_VERIFICADO")

    def test_schema_existente_divergente_sinalizado_sem_liberar_deploy(self):
        r=resultado(stage="SCHEMA_DIVERGENTE")
        self.assertEqual(r["stage_agro"],"SCHEMA_DIVERGENTE")
        self.assertFalse(r["libera_deploy"])
        self.assertIn("VIEW_FERROVIARIA_AUSENTE",resultado(view=None)["bloqueios"])

    def test_apenas_inventario_readonly_sem_criar_tabela(self):
        w=WORKFLOW.read_text(encoding="utf-8")
        source=SOURCE.read_text(encoding="utf-8")
        cli=SCRIPT.read_text(encoding="utf-8")
        self.assertIn("verificar_golive_gcp_readonly.py --executar",w)
        self.assertIn("bq.get_dataset(",source)
        self.assertIn("bq.get_table(",source)
        self.assertIn("storage.get_bucket(",source)
        self.assertIn('if not args.executar:',cli)
        for operation in (".create_dataset(",".create_table(",".insert_rows",
                          "bq.query(","gcloud services enable","run deploy"):
            self.assertNotIn(operation,source+cli+w)


if __name__=="__main__":
    unittest.main()
