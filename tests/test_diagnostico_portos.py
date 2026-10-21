import copy
import unittest

from nivon.diagnostico_portos import diagnosticar_portos
from nivon.catalogo_fontes import carregar_catalogo
from nivon.lineup_nacional import carregar_escopo
from nivon.rotas_coleta import carregar_rotas


class TestDiagnosticoPortos(unittest.TestCase):
    def test_escopo_contabiliza_35_e_10_sem_indicar_45_ativos(self):
        d=diagnosticar_portos()
        self.assertEqual(d["unidades_cadastradas"],45)
        self.assertEqual(d["portos_organizados"],35)
        self.assertEqual(d["tups_e_complexos_candidatos"],10)
        self.assertEqual(d["parsers_homologados"],0)
        self.assertEqual(d["coletas_ativas"],0)
        self.assertEqual(d["publicacoes_autorizadas"],0)
        self.assertGreaterEqual(d["paginas_ou_indices_candidatos"],9)

    def test_codeba_e_portosrio_nao_equivalem_coleta(self):
        d=diagnosticar_portos()
        portos={x["porto_id"]:x for x in d["unidades"]}
        self.assertEqual(portos["ARATU"]["estado"],"PAGINA_CANDIDATA_SEM_PARSER_HOMOLOGADO")
        self.assertEqual(portos["ITAGUAI"]["estado"],"INDICE_INSTITUCIONAL_SEM_DOCUMENTO_INDIVIDUAL")
        self.assertFalse(portos["FORNO"]["publicacao_autorizada"])
        self.assertTrue(portos["MIRITITUBA"]["estado"].startswith("TUP_OU_COMPLEXO"))

    def test_ausencia_de_rota_bloqueia_relatorio(self):
        cat=carregar_catalogo()
        scope=carregar_escopo()
        rotas=copy.deepcopy(carregar_rotas())
        rotas["entries"]=[x for x in rotas["entries"] if x["dataset_id"]!="LINEUP_ARATU"]
        with self.assertRaises(Exception):
            diagnosticar_portos(catalogo=cat,escopo=scope,rotas=rotas)


if __name__=="__main__":
    unittest.main()
