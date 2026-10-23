import copy
import unittest
from nivon.catalogo_fontes import carregar_catalogo
from nivon.rotas_coleta import carregar_rotas
from nivon.auditoria_coletores import auditoria_estatica

class TestAuditoriaColetores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat=carregar_catalogo()
        cls.rot=carregar_rotas()

    def test_cobertura_total_mantem_inventario_real(self):
        resultado=auditoria_estatica(self.cat,self.rot)
        self.assertEqual(resultado["total_auditado"],len(self.cat["datasets"]))
        self.assertEqual(resultado["total_catalogado"],len(self.cat["datasets"]))
        self.assertEqual(resultado["automaticos_habilitados"],0)
        self.assertEqual(resultado["prontos_para_producao"],0)
        self.assertFalse(any(x["publicacao_liberada"] for x in resultado["datasets"]))

    def test_cada_dataset_em_exatamente_uma_fase(self):
        r=auditoria_estatica(self.cat,self.rot)
        self.assertEqual(sum(r["por_fase"].values()),len(self.cat["datasets"]))
        self.assertEqual(len({x["dataset_id"] for x in r["datasets"]}),
                         len(self.cat["datasets"]))

    def test_p0_consistente_com_catalogo(self):
        r=auditoria_estatica(self.cat,self.rot,prioridade="P0")
        self.assertEqual(r["total_auditado"],
                         sum(x["priority"]=="P0" for x in self.cat["datasets"]))
        self.assertTrue(all(x["prioridade"]=="P0" for x in r["datasets"]))

    def test_source_restricted_nao_e_disfarced(self):
        r=auditoria_estatica(self.cat,self.rot)
        for x in r["datasets"]:
            if x["acesso_restrito"]:
                self.assertEqual(x["fase"],"DIREITOS_RESTRITOS")

    def test_nao_ativar_alterando_config(self):
        routes=copy.deepcopy(self.rot)
        routes["entries"][0]["scheduled_enabled"]=True
        with self.assertRaises(ValueError):
            auditoria_estatica(self.cat,routes)

    def test_bloqueio_de_endpoint_nao_permitido(self):
        routes=copy.deepcopy(self.rot)
        routes["entries"][0]["locator"]["url"]="http://evil.example"
        with self.assertRaises(ValueError):
            auditoria_estatica(self.cat,routes)

    def test_prioridade_incorreta(self):
        with self.assertRaises(ValueError):
            auditoria_estatica(self.cat,self.rot,prioridade="P3")

    def test_fases_nao_inferem_execucao_do_codigo(self):
        r=auditoria_estatica(self.cat,self.rot)
        for item in r["datasets"]:
            self.assertTrue(item["bloqueios"])
            self.assertFalse(item["coleta_automatica_habilitada"])

    def test_pagina_documentacao_nao_homologa_endpoint(self):
        r=auditoria_estatica(self.cat,self.rot)
        index={d["dataset_id"]:d for d in r["datasets"]}
        self.assertTrue(index["BCB_PTAX"]["recurso_tecnico_identificado"])
        self.assertTrue(index["MAPA_SIPEAGRO_RACAO"]["recurso_tecnico_identificado"])
        self.assertTrue(index["IBGE_PAM"]["recurso_tecnico_identificado"])
