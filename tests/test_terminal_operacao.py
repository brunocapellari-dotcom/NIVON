import copy
import json
import unittest
from unittest.mock import Mock
from nivon.terminal_operacao import diagnosticar

URL="https://nivon-terminal-test.southamerica-east1.run.app"
ENV={"NIVON_TERMINAL_URL":URL,"NIVON_GCP_COST_REVIEWED":"true",
     "NIVON_TERMINAL_READ_APPROVED":"true","NIVON_TERMINAL_EXPECTED_SHA":"a"*40}
SERVICE={"metadata":{"name":"nivon-terminal","labels":{"nivon-component":"terminal"}},
         "status":{"url":URL,"latestReadyRevisionName":"nivon-terminal-002",
                   "conditions":[{"type":"Ready","status":"True"}],
                   "traffic":[{"revisionName":"nivon-terminal-002","percent":100}],
                   "latestCreatedRevisionName":"nivon-terminal-002"},
         "spec":{"template":{"spec":{"containers":[{"image":
             "southamerica-east1-docker.pkg.dev/nivon-data/images/nivon-terminal:"+"a"*12}]}}}}
POLICY={"bindings":[{"role":"roles/run.invoker","members":["user:fixture@example.test"]}]}
PREVIOUS={"metadata":{"name":"nivon-terminal-001"},
          "status":{"conditions":[{"type":"Ready","status":"True"}]}}


def request(url,token):
    if token is None:return 403,{}
    if url.endswith('/healthz'):return 200,{"estado":"PROCESSO_ATIVO"}
    if url.endswith('/readyz'):return 200,{"estado":"PRONTO_PARA_LEITURA"}
    return 200,{"estado":"ANTT_SERIE_OBSERVADA_DECLARADA","natureza":"OBSERVADO_DECLARADO",
                "homologacao_editorial":False,"fonte":"ANTT/SIADE","ultima_competencia":"2026-08"}


class TestOperacao(unittest.TestCase):
    def run_check(self,**kwargs):
        args=dict(env=ENV,service=copy.deepcopy(SERVICE),policy=copy.deepcopy(POLICY),
                  previous=copy.deepcopy(PREVIOUS),executar=True,request=request,
                  token_provider=lambda _:"PRIVATE_TEST_TOKEN")
        args.update(kwargs)
        return diagnosticar(**args)

    def test_sucesso_sintetico_e_rollback_apenas_plano(self):
        out=self.run_check()
        self.assertTrue(out['smoke_ok'])
        self.assertTrue(out['rollback']['plano_validado'])
        self.assertFalse(out['rollback']['executado'])
        self.assertFalse(out['go_live'])
        self.assertNotIn('PRIVATE_TEST_TOKEN',json.dumps(out))

    def test_endpoint_desconhecido_custo_e_leitura_pendentes_sem_rede(self):
        for key in ENV:
            env=dict(ENV);env.pop(key)
            transport=Mock();token=Mock()
            self.assertFalse(self.run_check(env=env,request=transport,token_provider=token)['smoke_ok'])
            transport.assert_not_called();token.assert_not_called()

    def test_plano_nao_executa_rede_ou_token(self):
        transport=Mock();token=Mock()
        self.assertEqual(self.run_check(executar=False,request=transport,token_provider=token)['estado'],'PLANO_SEM_REDE')
        transport.assert_not_called();token.assert_not_called()

    def test_403_ou_401_autenticado_nao_e_sucesso(self):
        for status in (401,403,500):
            out=self.run_check(request=lambda u,t:(status,{}) if t else (403,{}))
            self.assertFalse(out['smoke_ok'])

    def test_rotas_publicas_interrompem_antes_do_token(self):
        token=Mock()
        out=self.run_check(request=lambda *_:(200,{}),token_provider=token)
        self.assertFalse(out['smoke_ok'])
        self.assertFalse(out['checks']['rotas_anonimas_bloqueadas'])
        token.assert_not_called()

    def test_falha_deploy_commit_e_iam_publico_sem_smoke(self):
        for change in ('revision','image','policy','iamdisabled','traffic','notready'):
            service=copy.deepcopy(SERVICE);policy=copy.deepcopy(POLICY)
            if change=='revision':service['status']['latestCreatedRevisionName']='nivon-terminal-failed'
            if change=='image':service['spec']['template']['spec']['containers'][0]['image']='other:latest'
            if change=='policy':policy['bindings'][0]['members']=['allUsers']
            if change=='iamdisabled':service['metadata']['annotations']={'run.googleapis.com/invoker-iam-disabled':'true'}
            if change=='traffic':service['status']['traffic'][0]['revisionName']='nivon-terminal-001'
            if change=='notready':service['status']['conditions'][0]['status']='False'
            transport=Mock()
            self.assertFalse(self.run_check(service=service,policy=policy,request=transport)['smoke_ok'])
            transport.assert_not_called()

    def test_revisao_anterior_invalida_nao_habilita_rollback(self):
        for previous in ({},SERVICE,{'metadata':{'name':'nivon-terminal-001'}}):
            self.assertFalse(self.run_check(previous=previous)['rollback']['plano_validado'])

    def test_erro_sanitizado_e_redirect_nao_e_auth_valida(self):
        out=self.run_check(request=Mock(side_effect=RuntimeError('PRIVATE_SECRET')))
        self.assertNotIn('PRIVATE_SECRET',json.dumps(out))
        self.assertFalse(out['smoke_ok'])
        self.assertFalse(self.run_check(request=lambda *_:(302,{}))['smoke_ok'])


if __name__=='__main__':unittest.main()
