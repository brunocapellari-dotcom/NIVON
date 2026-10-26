"""Pré-voo sem cloud: nenhum job SQL, deploy, token ou mudança de IAM."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

from nivon.terminal_preflight import diagnosticar, coletar_metadados, FalhaMetadados, GATES

SA = "terminal-reader@nivon-data.iam.gserviceaccount.com"
ENV = {"NIVON_PROJETO": "nivon-data", "NIVON_DATASET": "nivon_raw",
       "NIVON_TERMINAL_ARTIFACT_REPO": "nivon-images",
       "NIVON_TERMINAL_EXECUTION_SA": SA, **dict.fromkeys(GATES, "true")}
META = {
    "dataset": {"location": "southamerica-east1"}, "view": {"table_type": "VIEW"},
    "artifact": {"format": "DOCKER", "name": "projects/nivon-data/locations/southamerica-east1/repositories/nivon-images"},
    "service_account": {"email": SA}, "billing": {"billingEnabled": True},
    "project_policy": {"bindings": []}, "service_policy": {"bindings": []},
    "service": {"metadata": {"labels": {"nivon-component": "terminal"}},
                "spec": {"template": {"spec": {"serviceAccountName": SA}}}},
}


class TestTerminalPreflight(unittest.TestCase):
    def test_config_e_gates_antes_de_qualquer_rede(self):
        for key in ENV:
            with self.subTest(key=key):
                env = dict(ENV); env.pop(key)
                collector = Mock(side_effect=AssertionError("REDE_NAO_AUTORIZADA"))
                report = diagnosticar(env, executar=True, coletor=collector)
                self.assertFalse(report["ready_for_deploy"])
                self.assertEqual(report["estado"], "CONFIGURACAO_PENDENTE")
                collector.assert_not_called()

    def test_plano_nao_consulta_mesmo_com_gates(self):
        collector = Mock()
        report = diagnosticar(ENV, coletor=collector)
        self.assertEqual(report["estado"], "PLANO_SEM_REDE")
        self.assertFalse(report["ready_for_deploy"])
        collector.assert_not_called()

    def test_sucesso_simulado_nunca_e_go_live(self):
        report = diagnosticar(ENV, executar=True, coletor=lambda *_: copy.deepcopy(META))
        self.assertTrue(report["ready_for_deploy"])
        self.assertEqual(report["consultas_sql"], 0)
        self.assertEqual(report["gravacoes"], 0)
        self.assertFalse(report["go_live"])
        self.assertFalse(report["iam_efetivo_testado"])

    def test_falhas_de_recursos_e_billing(self):
        changes = [("billing", {"billingEnabled": False}), ("artifact", {}),
                   ("service_account", {"email": SA, "disabled": True}),
                   ("view", {"table_type": "TABLE"}), ("dataset", {"location": "US"}),
                   ("service", {}), ("service_policy", {}), ("project_policy", {})]
        for key, value in changes:
            with self.subTest(key=key):
                data = copy.deepcopy(META); data[key] = value
                report = diagnosticar(ENV, executar=True, coletor=lambda *_: data)
                self.assertFalse(report["ready_for_deploy"])

    def test_iam_publico_inclusive_herdado_bloqueia(self):
        for scope in ("project_policy", "service_policy"):
            for member in ("allUsers", "allAuthenticatedUsers"):
                data = copy.deepcopy(META)
                data[scope] = {"bindings": [{"role": "roles/run.invoker", "members": [member]}]}
                report = diagnosticar(ENV, executar=True, coletor=lambda *_: data)
                self.assertFalse(report["ready_for_deploy"])

    def test_invoker_iam_desabilitado_bloqueia(self):
        data = copy.deepcopy(META)
        data["service"]["metadata"]["annotations"] = {"run.googleapis.com/invoker-iam-disabled": "true"}
        self.assertFalse(diagnosticar(ENV, executar=True, coletor=lambda *_: data)["ready_for_deploy"])

    def test_erros_sanitizados_credencial_e_recurso_indisponivel(self):
        for exc in (RuntimeError("PRIVATE_TOKEN"), FalhaMetadados("CREDENCIAL_GCLOUD_AUSENTE"),
                    FalhaMetadados("ACESSO_OU_RECURSO_INDISPONIVEL"), KeyError("SECRET")):
            report = diagnosticar(ENV, executar=True, coletor=Mock(side_effect=exc))
            self.assertFalse(report["ready_for_deploy"])
            self.assertNotIn("PRIVATE_TOKEN", json.dumps(report))
            self.assertNotIn("SECRET", json.dumps(report))

    def test_valores_arbitrarios_de_ambiente_nao_sao_refletidos(self):
        env = dict(ENV); env["NIVON_TERMINAL_EXECUTION_SA"] = "SECRET; shell"
        report = diagnosticar(env, executar=True, coletor=Mock())
        self.assertNotIn("SECRET", json.dumps(report))
        self.assertFalse(report["ready_for_deploy"])

    def test_sem_conta_ativa_para_antes_de_importar_sdk(self):
        with patch("nivon.terminal_preflight._gcloud", return_value=[]) as cli:
            with self.assertRaisesRegex(FalhaMetadados, "CREDENCIAL_GCLOUD_AUSENTE"):
                coletar_metadados("nivon-images", SA)
            cli.assert_called_once_with("auth", "list", "--filter=status:ACTIVE")

    def test_comando_cli_sem_ferramenta_nao_vaza_stderr(self):
        from nivon.terminal_preflight import _gcloud
        with patch("nivon.terminal_preflight.subprocess.run", side_effect=FileNotFoundError("SECRET")):
            with self.assertRaisesRegex(FalhaMetadados, "GCLOUD_AUSENTE"):
                _gcloud("auth", "list")


if __name__ == "__main__":
    unittest.main()
