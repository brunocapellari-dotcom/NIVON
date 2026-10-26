"""Provar que o preflight Cloud Run é metadata-only e nunca implanta."""
import json
import unittest
from types import SimpleNamespace
from nivon.diagnostico_terminal_cloudrun import diagnosticar, descobrir_recursos_existentes, ErroDiagnostico

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


class CmdInventario(Cmd):
    def __call__(self, cmd, **kwargs):
        if cmd[:4] == ["gcloud","artifacts","repositories","list"]:
            self.calls.append(list(cmd))
            body=[
                {"name":"projects/nivon-data/locations/southamerica-east1/repositories/nivon-images",
                 "format":"DOCKER"},
                {"name":"projects/nivon-data/locations/southamerica-east1/repositories/raw-datasets",
                 "format":"GENERIC"},
                {"name":"projects/nivon-data/locations/southamerica-east1/repositories/nivon-images",
                 "format":"DOCKER"},
            ]
            return SimpleNamespace(returncode=0,stderr="",stdout=json.dumps(body))
        if cmd[:4] == ["gcloud","iam","service-accounts","list"]:
            self.calls.append(list(cmd))
            body=[{"email":SA, "disabled":False},
                  {"email":"old-disabled@nivon-data.iam.gserviceaccount.com",
                   "disabled":True},
                  {"email":"rogue@externo.iam.gserviceaccount.com",
                   "disabled":False}]
            return SimpleNamespace(returncode=0,stderr="",stdout=json.dumps(body))
        return super().__call__(cmd,**kwargs)


class TesteDescobertaSemAlteracoes(unittest.TestCase):
    def test_inventario_existente_metadados_apenas(self):
        run=CmdInventario()
        result=descobrir_recursos_existentes(runner=run)
        self.assertEqual(result["consulta_artifact_registry"],"CONFIRMADO")
        self.assertEqual(result["consulta_service_accounts"],"CONFIRMADO")
        self.assertEqual(result["repositorios_docker_existentes"],["nivon-images"])
        self.assertEqual(result["contas_existentes_necessitam_revisao_iam"],[SA])
        self.assertFalse(result["selecao_automatica"])
        self.assertFalse(result["autorizacao_de_deploy_verificada"])
        self.assertFalse(result["orcamento_verificado"])
        self.assertEqual(result["alteracoes_cloud"],0)
        self.assertEqual(len(run.calls),2)
        for cmd in run.calls:
            self.assertEqual(cmd[0],"gcloud")
            self.assertIn("list",cmd)
            self.assertNotIn("create",cmd)
            self.assertNotIn("deploy",cmd)
            self.assertNotIn("delete",cmd)

    def test_preflight_descobre_mas_nao_promove_sem_variaveis(self):
        run=CmdInventario(missing="run services describe")
        result=diagnosticar(runner=run,reader=Client(),descobrir_candidatos=True)
        self.assertEqual(result["componentes"]["artifact_repository"],"NAO_CONFIGURADO")
        self.assertEqual(result["componentes"]["execution_service_account"],"NAO_CONFIGURADO")
        self.assertFalse(result["metadados_basicos_confirmados"])
        self.assertFalse(result["go_live_homologado"])
        self.assertFalse(result["permissao_de_escrita_verificada"])
        self.assertEqual(result["descoberta_candidatos"]["repositorios_docker_existentes"],["nivon-images"])
        self.assertEqual(result["descoberta_candidatos"]["contas_existentes_necessitam_revisao_iam"],[SA])

    def test_configuracao_ja_informada_nao_lista_recursos_desnecessariamente(self):
        run=Cmd()
        result=diagnosticar(
            repositoriodeimagens="nivon-images",contaexecucao=SA,
            runner=run,reader=Client(),descobrir_candidatos=True,
        )
        self.assertTrue(result["metadados_basicos_confirmados"])
        self.assertIsNone(result["descoberta_candidatos"])
        self.assertEqual(len(run.calls),7)

    def test_falhas_de_descoberta_nao_viram_aprovacao(self):
        class Deny:
            def __call__(self,cmd,**kwargs):
                return SimpleNamespace(returncode=1,stderr="403 permission denied",stdout="")
        x=descobrir_recursos_existentes(runner=Deny())
        self.assertEqual(x["consulta_artifact_registry"],"SEM_PERMISSAO")
        self.assertEqual(x["consulta_service_accounts"],"SEM_PERMISSAO")
        self.assertEqual(x["repositorios_encontrados"],0)
        self.assertEqual(x["contas_encontradas"],0)
        self.assertFalse(x["selecao_automatica"])


if __name__=="__main__":unittest.main()
