import copy
import unittest
from nivon.auditoria_prontidao import diagnostico_atual, auditar_prontidao
from nivon.catalogo_fontes import carregar_catalogo, ErroCatalogo
from nivon.rotas_coleta import carregar_rotas
from nivon.cobertura import carregar_matriz
from nivon.registro_motores import carregar_registro
from nivon.lineup_nacional import carregar_escopo


class TestAuditoriaProntidao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=carregar_catalogo()
        cls.r=carregar_rotas()
        cls.m=carregar_matriz(catalogo=cls.c)
        cls.e=carregar_registro()
        cls.esc=carregar_escopo()

    def test_diagnostico_nao_afirma_go_live(self):
        x=diagnostico_atual()
        self.assertEqual(x["datasets"],131)
        self.assertEqual(x["lineups_catalogados"],45)
        self.assertEqual(x["frentes"],28)
        self.assertEqual(x["coletas_operacionais"],0)
        self.assertEqual(x["motores_preditivos_homologados"],0)
        self.assertGreaterEqual(x["funcoes_vinculadas"],100)
        self.assertEqual(x["status"],"BLOQUEADO_PARA_GO_LIVE")
        self.assertEqual(sum(x["datasets_por_estagio"].values()),131)
        self.assertEqual(len(x["datasets_detalhados"]),131)

    def test_bloqueio_ativacao_clandestina(self):
        c=copy.deepcopy(self.c);c["datasets"][0]["enabled"]=True
        with self.assertRaises(ErroCatalogo):
            auditar_prontidao(c,self.r,self.m,self.e,self.esc)

    def test_direitos_restritos_nao_disponiveis(self):
        x=diagnostico_atual()
        self.assertGreater(x["direitos_restritos_pendentes"],0)
        bloqueados=[d for d in x["datasets_detalhados"] if d["stage"]=="BLOCKED_RIGHTS"]
        self.assertTrue(all(not d["operacional"] for d in bloqueados))

    def test_sistema_nao_aceita_lineup_faltando(self):
        esc=copy.deepcopy(self.esc)
        esc["ports"].pop()
        with self.assertRaises(ErroCatalogo):
            auditar_prontidao(self.c,self.r,self.m,self.e,esc)

    def test_fonte_com_codigo_nao_vira_rodando(self):
        r=diagnostico_atual()
        coded=[d for d in r["datasets_detalhados"] if d["stage"]=="CODE_PRESENT"]
        self.assertTrue(coded)
        self.assertTrue(all(d["parser_mapeado"] and not d["operacional"] for d in coded))

    def test_mapeamento_porto_dataset_um_a_um(self):
        esc=copy.deepcopy(self.esc)
        esc["ports"][0]["id"]="PORTO_FAKE_XX"
        with self.assertRaises(ErroCatalogo):
            auditar_prontidao(self.c,self.r,self.m,self.e,esc)


if __name__=="__main__":
    unittest.main()
