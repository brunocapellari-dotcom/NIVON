"""Gates da auditoria C1 — testes offline e sem permissao de escrita."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AuditoriaC1(unittest.TestCase):
    def texto(self, arquivo):
        return (ROOT / arquivo).read_text(encoding="utf-8")

    def test_ptax_branch_antiga_e_evento_invalido_bloqueados(self):
        s=self.texto("functions/ptax_private_export/index.mjs")
        self.assertNotIn("refs/heads/plan/gcp-data-platform-20261021",s)
        self.assertIn("const ALLOWED=new Set(['refs/heads/main'])",s)
        self.assertIn("'schedule','workflow_dispatch'",s)

    def test_pipeline_rejeita_parcial_antes_de_arquivar_e_exige_manifesto(self):
        s=self.texto(".github/workflows/coleta-recorrente-fontes.yml")
        self.assertIn("vars.NIVON_RECOVERABLE_STAGE_APPROVED == 'true'",s)
        self.assertNotIn("if: ${{ vars.NIVON_RECOVERABLE_STAGE_APPROVED == 'true' }}",s)
        self.assertLess(s.index("Reprovar coleta parcial antes"),s.index("Arquivar todos os RAWs"))
        self.assertLess(s.index("Arquivar stage e manifesto"),s.index("Carregar observacoes com MERGE"))

    def test_replay_verifica_conteudo_remoto_nao_so_metadata(self):
        s=self.texto("src/nivon/lote_cloud_recuperavel.py")
        self.assertIn("objeto.download_to_filename",s)
        self.assertIn("_sha(local) != sha",s)
        raw=self.texto("src/nivon/arquivo_raw_gcs.py")
        self.assertIn("verificar_bytes(existe, item)",raw)

    def test_stage_tem_ttl_e_bq_registra_linhas_afetadas(self):
        s=self.texto("src/nivon/carga_bigquery_fontes.py")
        self.assertIn("timedelta(hours=6)",s)
        self.assertIn("num_dml_affected_rows",s)
        self.assertIn("job_id",s)

    def test_migracao_neon_sem_update_destrutivo(self):
        s=self.texto("scripts/nivon_gcp_migracao.py")
        self.assertNotIn("WHEN MATCHED AND T.payload_sha256",s)
        self.assertIn("CONFLITO_VINTAGE_ORIGEM",s)
        self.assertIn("WHERE T.payload_sha256 != S.payload_sha256",s)

    def test_diagnostico_api_cloud_nao_habilita_servicos(self):
        s=self.texto(".github/workflows/maritimo-gcp-api-bootstrap.yml")
        self.assertNotIn("gcloud services enable",s)
        self.assertNotIn("id-token: write",s)
        self.assertNotIn("google-github-actions/auth",s)

    def test_ddl_tem_filtro_de_particao(self):
        s=self.texto("sql/bigquery/002_observacoes_fontes_reais.sql")
        self.assertIn("require_partition_filter=true",s)


if __name__ == "__main__":
    unittest.main()
