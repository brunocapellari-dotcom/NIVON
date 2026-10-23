import copy
import unittest
from nivon.catalogo_fontes import carregar_catalogo, ErroCatalogo
from nivon.orquestrador_fontes import plano, WORKFLOW


class TestOrquestradorSemColeta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogo=carregar_catalogo()

    def test_todos_bloqueados_por_padrao(self):
        r=plano(self.catalogo,incluir_restritas=True)
        self.assertEqual(r["ativos"],0)
        self.assertEqual(r["sem_autorizacao_operacional"],r["coletores"])
        self.assertTrue(all(d["executar"] is False for d in r["plano"]))

    def test_restritas_nao_entram_no_plano_padrao(self):
        all_=plano(self.catalogo,incluir_restritas=True)
        sem=plano(self.catalogo)
        self.assertGreater(all_["coletores"],sem["coletores"])
        self.assertFalse(any(d["estado"]=="PENDENTE_LICENCA" for d in sem["plano"]))

    def test_prioriza_p0_primeiro(self):
        r=plano(self.catalogo)
        prioridades=[x["prioridade"] for x in r["plano"]]
        self.assertEqual(prioridades,sorted(prioridades))

    def test_plano_diesel_retorna_coletores_diesel(self):
        r=plano(self.catalogo,grupo="ENERGIA")
        self.assertTrue(any(x["dataset"]=="ANP_PRECO_REVENDA_DIESEL" for x in r["plano"]))

    def test_plano_usa_pipeline_11_gates(self):
        self.assertEqual(len(WORKFLOW),11)
        self.assertIn("licence_and_operation",WORKFLOW)
        self.assertIn("persist_and_backup",WORKFLOW)

    def test_catalogo_adulterado_nao_habilita(self):
        j=copy.deepcopy(self.catalogo)
        j["datasets"][0]["enabled"]=True
        with self.assertRaises(ErroCatalogo):
            plano(j,incluir_restritas=True)

    def test_prioridade_fora_do_contrato_bloqueada(self):
        with self.assertRaises(ErroCatalogo):
            plano(self.catalogo,prioridade="P99")


if __name__=="__main__":
    unittest.main()
