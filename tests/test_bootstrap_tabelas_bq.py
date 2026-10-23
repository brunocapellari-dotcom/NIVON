"""Bootstrap GCP: ordem dos gates, criação controlada e verificação readback."""
import unittest
from nivon.bootstrap_tabelas_bq import executar_bootstrap, ErroBootstrap

BASE={"projeto":"nivon-data","dataset":"nivon_raw","bucket":"nivon-data-raw-2026"}
GATES={
    "NIVON_ZERO_COST_BQ_APPROVED":"true",
    "NIVON_BQ_BOOTSTRAP_TABLE_APPROVED":"true",
    "NIVON_AGRO_STAGING_SCHEMA_APPROVED":"true",
    "NIVON_AGRO_GCP_WRITE_APPROVED":"true",
}
NOMES=("nivon_observacoes","agro_publicacoes_staging")


class AmbienteSimulado:
    def __init__(self,canon=False,agro=False,regiao=True,corrompido=None):
        self.tabelas={NOMES[0]:canon,NOMES[1]:agro}
        self.regiao=regiao
        self.corrompido=corrompido
        self.leituras=0
        self.criacoes=[]
        self.chamadas=[]

    def ler(self,**kwargs):
        self.leituras+=1
        return {"acesso_metadados_confirmado":True,
                "regiao_conforme":self.regiao,
                "tabelas":[{"tabela":n,"existe":self.tabelas[n],
                    "schema_conforme":n!=self.corrompido and self.tabelas[n],
                    "particao_conforme":n!=self.corrompido and self.tabelas[n]}
                    for n in NOMES]}

    def canon(self,*,projeto,dataset,bucket,criar_tabela):
        self.chamadas.append(("canon",criar_tabela))
        if criar_tabela:
            self.tabelas[NOMES[0]]=True
            self.criacoes.append(NOMES[0])
        return {"tabela_validada":True,"tabela_criada":criar_tabela}

    def agro(self,*,projeto,dataset,verificar,aplicar,aprovado):
        self.chamadas.append(("agro",aplicar,aprovado))
        if aplicar:
            self.tabelas[NOMES[1]]=True
            self.criacoes.append(NOMES[1])
        return {"criou_tabela":aplicar,"estado":"TABELA_CONFORME"}

    def run(self,**kwargs):
        return executar_bootstrap(**BASE,leitura=self.ler,
            bootstrap_canonico=self.canon,bootstrap_agro=self.agro,**kwargs)


class BootstrapE2ETest(unittest.TestCase):
    def test_leitura_sem_escrita_com_tabelas_ausentes(self):
        e=AmbienteSimulado()
        ret=e.run()
        self.assertEqual(ret["estado"],"VERIFICACAO_SOMENTE_LEITURA")
        self.assertEqual(set(ret["tabelas_pendentes"]),set(NOMES))
        self.assertFalse(ret["executou_escrita"])
        self.assertEqual(e.leituras,1)
        self.assertEqual(e.criacoes,[])

    def test_aprovacoes_ausentes_bloqueiam_antes_primeira_escrita(self):
        e=AmbienteSimulado()
        with self.assertRaises(PermissionError):
            e.run(aplicar=True,env={})
        self.assertEqual(e.criacoes,[])
        self.assertEqual(e.chamadas,[])
        with self.assertRaises(PermissionError):
            e.run(aplicar=True,env={k:v for k,v in GATES.items()
                                   if k!="NIVON_AGRO_GCP_WRITE_APPROVED"})
        self.assertEqual(e.criacoes,[])

    def test_apply_e_reexecucao_idempotente(self):
        e=AmbienteSimulado()
        ret=e.run(aplicar=True,env=GATES)
        self.assertEqual(ret["estado"],"SCHEMAS_CONFIRMADOS_SEM_DADOS")
        self.assertEqual(ret["criou_tabelas"],list(NOMES))
        self.assertTrue(ret["executou_escrita"])
        self.assertFalse(ret["pronto_para_producao"])
        self.assertEqual(e.leituras,2)
        again=e.run(aplicar=True,env=GATES)
        self.assertEqual(again["criou_tabelas"],[])
        self.assertFalse(again["executou_escrita"])
        self.assertEqual(e.criacoes,list(NOMES))

    def test_tabela_existente_invalida_bloqueia_outra_criacao(self):
        e=AmbienteSimulado(canon=True,agro=False,corrompido=NOMES[0])
        with self.assertRaises(ErroBootstrap):
            e.run(aplicar=True,env=GATES)
        self.assertEqual(e.criacoes,[])

    def test_regiao_errada_bloqueia_criacao(self):
        e=AmbienteSimulado(regiao=False)
        with self.assertRaises(ErroBootstrap):
            e.run(aplicar=True,env=GATES)
        self.assertFalse(e.criacoes)

    def test_bootstrap_apenas_canonico_so_exige_seus_gates(self):
        e=AmbienteSimulado()
        gates={k:GATES[k] for k in
               ("NIVON_ZERO_COST_BQ_APPROVED","NIVON_BQ_BOOTSTRAP_TABLE_APPROVED")}
        ret=e.run(aplicar=True,alvo="canonico",env=gates)
        self.assertEqual(ret["criou_tabelas"],[NOMES[0]])
        self.assertFalse(e.tabelas[NOMES[1]])

    def test_readback_obrigatorio(self):
        e=AmbienteSimulado()
        def leitura_falsa(**kwargs):
            resultado=e.ler(**kwargs)
            if e.leituras>1:
                resultado["tabelas"][0]["particao_conforme"]=False
            return resultado
        with self.assertRaises(ErroBootstrap):
            executar_bootstrap(**BASE,aplicar=True,env=GATES,leitura=leitura_falsa,
                    bootstrap_canonico=e.canon,bootstrap_agro=e.agro)
        self.assertEqual(e.criacoes,list(NOMES))

if __name__=="__main__":
    unittest.main()
