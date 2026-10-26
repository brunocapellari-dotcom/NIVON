"""Aceite da fase 1: piloto ferroviario isolado do stage Agro e de deploy."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from nivon.prontidao_golive_piloto import consultar_metadados

ROOT=Path(__file__).resolve().parents[1]
WF=ROOT/".github"/"workflows"

class NotFound(Exception): pass

class BQ:
    def __init__(self,view=True,stage=False):
        self.view=view;self.stage=stage;self.calls=[]
    def get_dataset(self,p):
        self.calls.append(p);return SimpleNamespace(location="southamerica-east1")
    def get_table(self,p):
        self.calls.append(p)
        if p.endswith("vw_antt_ferrovia_od_atual"):
            if not self.view:raise NotFound()
            return SimpleNamespace(table_type="VIEW")
        if p.endswith("agro_fonte_stage"):
            if not self.stage:raise NotFound()
            return SimpleNamespace(schema=[
                SimpleNamespace(name="coletado_utc",field_type="TIMESTAMP")],
                time_partitioning=SimpleNamespace(field="coletado_utc"))
        raise AssertionError("consulta fora da allowlist")

class GCS:
    def __init__(self,pap="enforced"):self.pap=pap
    def get_bucket(self,p):
        return SimpleNamespace(location="southamerica-east1",
            iam_configuration=SimpleNamespace(public_access_prevention=self.pap))

def audit(bq=None,gcs=None):
    return consultar_metadados(bq=bq or BQ(),storage=gcs or GCS(),
        erro_nao_encontrado=NotFound,tipos_stage={"coletado_utc":"TIMESTAMP"})

class TestGoLive(unittest.TestCase):
    def test_view_antt_pronta_independente_de_stage_agro(self):
        bq=BQ();r=audit(bq)
        self.assertEqual(r["estado"],"PILOTO_DADOS_READONLY_PRONTO")
        self.assertEqual(r["stage_agro"],"AUSENTE")
        self.assertEqual(r["consultas_sql_executadas"],0)
        self.assertFalse(r["libera_deploy"])
        self.assertEqual(r["terminal_cloud_run_implantado"],"NAO_VERIFICADO")
        self.assertEqual(len(bq.calls),3)

    def test_stage_presente_e_validada(self):
        self.assertEqual(audit(BQ(stage=True))["stage_agro"],"SCHEMA_OK")

    def test_view_ausente_e_bucket_publico_reprovam(self):
        self.assertIn("VIEW_FERROVIARIA_AUSENTE",audit(BQ(view=False))["bloqueios"])
        self.assertIn("BUCKET_SEM_PUBLIC_ACCESS_PREVENTION",
            audit(gcs=GCS("inherited"))["bloqueios"])

    def test_forbidden_nao_pode_ser_tratado_como_ausente(self):
        class Forbidden(BQ):
            def get_table(self,p):
                if p.endswith("agro_fonte_stage"):raise PermissionError()
                return super().get_table(p)
        with self.assertRaises(PermissionError):audit(Forbidden())

    def test_cli_dryrun_nao_faz_rede_ou_publicacao(self):
        r=subprocess.run([sys.executable,
            str(ROOT/"scripts"/"verificar_golive_gcp_readonly.py")],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout)["estado"],"PLANO_SEM_REDE")

    def test_publicacao_gcs_so_com_dupla_aprovacao(self):
        w=(WF/"nivon-go-live-interno.yml").read_text()
        gate=w.split("  primeira-publicacao:",1)[1].split("    runs-on:",1)[0]
        self.assertIn("NIVON_PAINEL_INTERNO_WRITE_APPROVED == 'true'",gate)
        self.assertIn("NIVON_GCP_COST_REVIEWED == 'true'",gate)
        self.assertIn("NIVON_PAINEL_INTERNO_AGENDADO == 'true'",gate)
        self.assertNotIn("github.event_name == 'push'",gate)

    def test_consulta_real_somente_manual_aprovada(self):
        w=(WF/"nivon-terminal-piloto-real.yml").read_text()
        gate=w.split("  piloto-real:",1)[1].split("    runs-on:",1)[0]
        for s in ("github.event_name == 'workflow_dispatch'",
                  "NIVON_TERMINAL_READ_APPROVED == 'true'",
                  "NIVON_GCP_COST_REVIEWED == 'true'"):
            self.assertIn(s,gate)

    def test_workflow_readonly_reporta_stage_separadamente(self):
        w=(WF/"nivon-go-live-readonly.yml").read_text()
        self.assertIn("verificar_golive_gcp_readonly.py --executar",w)
        self.assertIn("stage_agro",w)
        self.assertIn("PILOTO_DADOS_READONLY_PRONTO",w)
        self.assertNotIn("--criar-tabela",w)

if __name__=="__main__":unittest.main()
