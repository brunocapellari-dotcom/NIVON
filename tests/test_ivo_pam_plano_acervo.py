"""IVO: plano documental de correção real sem preencher números ausentes."""
import unittest
from datetime import date

from nivon.ivo_radar_erratas_pam import carregar_erratas_pam
from nivon.ivo_pam_plano_acervo import plano_evidencias_errata_pam

def plano(*,ano=2021,municipio_ibge="5107958",categoria_c81="2713",
          corte=date(2026,10,21)):
    return plano_evidencias_errata_pam(catalogo=carregar_erratas_pam(),
        municipio_ibge=municipio_ibge,ano=ano,categoria_c81=categoria_c81,
        variavel="214",corte=corte)

class TestIVOPlanoAcervoPAM(unittest.TestCase):
    def test_tangara_soja_2021_discovery_gera_pedido_pontual_exato(self):
        r=plano()
        self.assertEqual(r["avisos"],1)
        self.assertEqual(r["alvo"]["produto"],"SOJA_EM_GRAO")
        tarefas={x["id"]:x for x in r["tarefas"][0]["tarefas"]}
        self.assertEqual(tarefas["SIDRA_ESTADO_ATUAL"]["url"],
            "https://apisidra.ibge.gov.br/values/t/1612/n6/5107958/v/214/p/2021/c81/2713/h/y/f/a")
        self.assertIsNone(tarefas["SIDRA_ANTES_DA_ERRATA"]["url"])
        self.assertFalse(r["valores_anteriores_recuperados"])
        self.assertFalse(r["arquivos_numericos_baixados"])
        self.assertFalse(r["homologacao_do_modelo"])

    def test_antes_da_errata_plano_nao_vaza_consulta_corrigida(self):
        r=plano(corte=date(2026,8,1))
        tarefas={x["id"]:x for x in r["tarefas"][0]["tarefas"]}
        self.assertIsNone(tarefas["SIDRA_ESTADO_ATUAL"]["url"])
        self.assertEqual(tarefas["SIDRA_ESTADO_ATUAL"]["estado"],
                         "BLOQUEADO_POR_DATA")

    def test_producao_municipal_nao_confundida_com_lspa_mensal(self):
        r=plano()
        filhos=r["pesquisa_complementar"]
        self.assertEqual(filhos[0]["papel"],"DIRETORIO_DE_PAM_ANUAL_LEGADA")
        self.assertEqual(filhos[1]["papel"],"ARQUIVO_DE_BOLETINS_LSPA_MENSAIS")
        self.assertFalse(filhos[0]["comprovacao_vintage_2021"])
        self.assertFalse(filhos[1]["comprovacao_vintage_2021"])

    def test_municipio_sem_aviso_nao_recebe_errata_inventada(self):
        r=plano(municipio_ibge="5107925")
        self.assertEqual(r["avisos"],0)
        self.assertEqual(r["tarefas"],[])

    def test_arandu_sorgo_restringe_anos(self):
        for ano in (2020,2022,2023):
            r=plano(municipio_ibge="3503109",categoria_c81="2714",ano=ano)
            self.assertEqual(r["avisos"],1)
            self.assertEqual(r["alvo"]["produto"],"SORGO_EM_GRAO")
        self.assertEqual(plano(municipio_ibge="3503109",categoria_c81="2714",
                               ano=2021)["avisos"],0)

    def test_soja_e_sorgo_nao_sao_intercambiaveis(self):
        self.assertEqual(plano(categoria_c81="2714")["avisos"],0)

if __name__=="__main__":
    unittest.main()
