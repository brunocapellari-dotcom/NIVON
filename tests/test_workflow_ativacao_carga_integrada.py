"""Regressões do workflow GCP: nenhum fluxo de dados sem gates de aprovação."""
from pathlib import Path
import unittest

PATH=Path(__file__).resolve().parents[1]/".github/workflows/ativar-tabelas-nivon-gcp.yml"

class TestAtivacaoCloudIntegra(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.yaml=PATH.read_text(encoding="utf-8")

    def test_manual_sem_agendamento_ou_ativacao_silenciosa(self):
        y=self.yaml
        self.assertIn("workflow_dispatch:",y)
        self.assertNotIn("  schedule:",y)
        self.assertIn("default: false",y)
        self.assertIn("default: NENHUMA",y)
        self.assertIn("github.ref == 'refs/heads/main'",y)
        self.assertIn("environment: nivon-gcp-producao",y)

    def test_tabela_gates_independentes(self):
        y=self.yaml
        for gate in (
            "NIVON_BQ_BOOTSTRAP_TABLE_APPROVED",
            "NIVON_AGRO_STAGING_SCHEMA_APPROVED",
            "NIVON_AGRO_GCP_WRITE_APPROVED",
            "NIVON_ZERO_COST_BQ_APPROVED",
        ):
            self.assertIn('test "$'+gate+'" == \'true\'',y)
        self.assertLess(y.index("Impedir criação sem aprovação"),
                        y.index("uses: google-github-actions/auth@"))

    def test_cada_fonte_tem_gate_individual(self):
        y=self.yaml
        for name in ("NENHUMA","BCB_SGS11","IMEA","CONAB",
                     "CEPEA_SOJA","CEPEA_MILHO"):
            self.assertIn(f"          - {name}",y)
        for gate in (
            "NIVON_SGS11_GCP_WRITE_APPROVED",
            "NIVON_SGS11_EVIDENCIA_USO",
            "NIVON_IMEA_FONTE_AUTORIZADA",
            "NIVON_CONAB_FONTE_AUTORIZADA",
            "NIVON_CEPEA_FONTE_AUTORIZADA",
            "NIVON_CEPEA_HOMOLOGACAO_APROVADA",
            "NIVON_AGRO_STAGING_BIGQUERY_APPROVED",
            "NIVON_RAW_ARCHIVE_APPROVED",
        ):
            self.assertIn(gate,y)
        self.assertIn('[[ "$NIVON_APLICAR" == "true"',y)

    def test_reutiliza_coletores_sem_pipeline_paralelo(self):
        y=self.yaml
        for cmd in (
            "python -m nivon.bootstrap_tabelas_gcp",
            "python -m nivon.sgs11_gcp --executar",
            "python scripts/coletar_agro_google_cloud.py",
            "--staging-bigquery",
            "--homologar-cepea --bigquery",
        ):
            self.assertIn(cmd,y)
        self.assertNotIn("neon.tech",y)
        self.assertIn("checkout@11bd71901bbe5b1630ceea73d27597364c9af683",y)

    def test_sem_carga_quando_aplicar_false(self):
        y=self.yaml
        self.assertIn("if: $" + "{{ inputs.aplicar && inputs.primeira_fonte != 'NENHUMA' }}",y)
        self.assertLess(y.index("Verificar ou criar somente tabelas"),
                        y.index("Primeira carga única"))
        self.assertLess(y.index("Validar autorização individual"),
                        y.index("Verificar ou criar somente tabelas"))

if __name__=="__main__":
    unittest.main()
