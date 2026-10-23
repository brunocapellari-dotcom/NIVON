"""Contratos de segurança da coleta agendada IVO PAM e backup GCS.

Não faz HTTP e não exige GCP; impede regressões em backup, agendamento,
identidade federada e prevenção de perda de estado já coletado.
"""
from pathlib import Path
import unittest

WORKFLOW=Path(__file__).resolve().parents[1]/".github/workflows/ivo-pam-piloto.yml"


class TestIVOPAMGCSWorkflow(unittest.TestCase):
    def setUp(self):
        self.w=WORKFLOW.read_text(encoding="utf-8")

    def test_rede_nao_roda_automaticamente_em_pr_ou_push(self):
        header=self.w.split("permissions:",1)[0]
        self.assertNotIn("pull_request:",header)
        self.assertNotIn("push:",header)
        self.assertIn("workflow_dispatch:",header)
        self.assertIn("schedule:",header)

    def test_wif_so_permitido_no_branch_principal_com_tres_variaveis(self):
        w=self.w
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"',w)
        self.assertIn('test -n "$GCS_BUCKET"',w)
        self.assertIn('test -n "$GCS_PROVIDER"',w)
        self.assertIn('test -n "$GCS_SERVICE"',w)
        self.assertIn("if: steps.gcs.outputs.active == 'true'",w)
        self.assertIn("id-token: write",w)
        self.assertIn("token_format: access_token",w)
        self.assertIn("google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093",w)
        self.assertNotIn("credentials_json:",w)
        self.assertNotIn("create-key",w)

    def test_cloud_restaurado_antes_de_coleta_e_upload_depois_da_auditoria(self):
        w=self.w
        a=w.index("name: Recuperar ultimo backup GCS")
        b=w.index("name: Restaurar ultima cadeia de backup aprovada")
        c=w.index("name: Atualizar mesmo historico")
        d=w.index("name: Publicar backup imutavel GCS")
        e=w.index("name: Preservar backup validado")
        self.assertTrue(a<b<c<d<e)
        self.assertIn("PAM_PRIOR=$BASE/anterior/estado_pam.zip",w)
        self.assertIn("python -m nivon.ivo_pam_storage_gcs upload",w)
        self.assertIn("python -m nivon.ivo_pam_storage_gcs recuperar",w)

    def test_sem_storage_nao_inventa_credencial_nem_perde_historico(self):
        w=self.w
        self.assertIn('ARMAZENAMENTO_GCS=DESABILITADO_NESTE_BRANCH',w)
        self.assertIn('GCS inacessivel/corrompido ou bootstrap nao autorizado',w)
        self.assertIn("BOOTSTRAP_AUTORIZADO",w)
        self.assertIn("PAM_CLOUD_BOOTSTRAP=1",w)
        self.assertIn("O ciclo $run_id foi concluido, mas seu backup atual nao esta disponivel",w)

    def test_primeiro_main_exige_safra_historica_real_24_capturas(self):
        w=self.w
        self.assertIn('gh run download 39946796466',w)
        self.assertIn("SEMENTE_MT_24_CAPTURAS",w)
        self.assertIn("Migracao sem a semente auditada de 24 capturas",w)
        self.assertIn("retention-days: 30",w)


if __name__=="__main__":
    unittest.main()
