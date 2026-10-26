"""Provar que o preflight Cloud Run é metadata-only e nunca implanta."""
import json
import unittest
from types import SimpleNamespace
from nivon.diagnostico_terminal_cloudrun import diagnosticar, ErroDiagnostico

SA="terminal-readonly@nivon-data.iam.gserviceaccount.com"

class Client:
    def get_dataset(self,key):
        return SimpleNamespace(location="southamerica-east1")
    def get_table(self,key):
        return SimpleNamespace(table_type="VIEW")

class Cmd:
    def __init__(self,missing=None,public=False):
        self.calls=[];self.missing=missing or "";self.public=public
    def __call__(self,cmd,**kwargs):
        self.calls.append(list(cmd))
        self._policy="-iam-policy" in " ".join(cmd) or "get-iam-policy" in cmd
        joined=" ".join(cmd)
        if self.missing in joined and self.missing:
            return SimpleNamespace(returncode=1,stderr="404 Not found",stdout="")
        if cmd[:3]==["gcloud","services","describe"]:
            body={"state":"ENABLED"}
        elif "repositories describe" in joined:
            body={"format":"DOCKER"}
        elif "service-accounts describe" in joined:
            body={"email":SA,"disabled":False}
        elif "get-iam-policy" in joined:
            body={"bindings":[{"role":"roles/run.invoker",
                 "members":["allUsers" if self.public else "user:operator@example.com"]}]}
        else:
            body={"metadata":{"labels":{"nivon-component":"terminal"}}}
        return SimpleNamespace(returncode=0,stderr="",stdout=json.dumps(body))

class TesteDiagnostico(unittest.TestCase):
    def test_preflight_sem_nenhum_comando_mutante(self):
        runner=Cmd()
        result=diagnosticar(repositoriodeimagens="nivon-registry",
                           contaexecucao=SA,runner=runner,reader=Client())
        self.assertTrue(result["metadados_basicos_confirmados"])
        self.assertFalse(result["autorizacao_de_deploy_verificada"])
        self.assertFalse(result["go_live_homologado"])
        self.assertFalse(result["sql_executado"])
        self.assertEqual(result["alteracoes_cloud"],0)
        for cmd in runner.calls:
            self.assertEqual(cmd[0],"gcloud")
            self.assertFalse(any(s in cmd for s in
                ["create","deploy","enable","builds","submit","set-iam-policy"]))
        self.assertEqual(len(runner.calls),7)

    def test_repo_ausente_bloqueia_readiness(self):
        runner=Cmd(missing="repositories describe")
        result=diagnosticar(repositoriodeimagens="nivon-registry",
                           contaexecucao=SA,runner=runner,reader=Client())
        self.assertEqual(result["componentes"]["artifact_repository"],"AUSENTE")
        self.assertFalse(result["metadados_basicos_confirmados"])

    def test_cloudrun_existente_publico_bloqueia(self):
        runner=Cmd(public=True)
        result=diagnosticar(repositoriodeimagens="nivon-registry",
                           contaexecucao=SA,runner=runner,reader=Client())
        self.assertEqual(result["componentes"]["terminal_iam_privado"],"DIVERGENTE")
        self.assertFalse(result["metadados_basicos_confirmados"])

    def test_parametros_nao_confiaveis_rejeitados_antes_de_rede(self):
        with self.assertRaises(ErroDiagnostico):
            diagnosticar(repositoriodeimagens="foo;rm",contaexecucao=SA,runner=Cmd(),reader=Client())
        with self.assertRaises(ErroDiagnostico):
            diagnosticar(repositoriodeimagens="nivon-registry",
                         contaexecucao="root@example.com",runner=Cmd(),reader=Client())

    def test_config_faltando_nao_inventa_prontidao(self):
        runner=Cmd(missing="services describe")
        result=diagnosticar(runner=runner,reader=Client())
        self.assertEqual(result["componentes"]["execution_service_account"],"NAO_CONFIGURADO")
        self.assertEqual(result["componentes"]["artifact_repository"],"NAO_CONFIGURADO")
        self.assertFalse(result["metadados_basicos_confirmados"])

if __name__=="__main__":unittest.main()
