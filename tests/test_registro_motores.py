import copy
import unittest

from nivon.catalogo_fontes import ErroCatalogo, carregar_catalogo
from nivon.cobertura import carregar_matriz, validar_matriz
from nivon.registro_motores import carregar_registro, validar_registro


class TestRegistroMotores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat=carregar_catalogo()
        cls.m=carregar_matriz(catalogo=cls.cat)
        cls.r=carregar_registro()

    def test_motores_em_todas_28_frentes_e_252_indicadores_minimos(self):
        mm=validar_matriz(self.m,self.cat)
        self.assertEqual(mm["frentes"],28)
        self.assertGreaterEqual(mm["indicadores"],250)
        d=validar_registro(self.r,self.m)
        self.assertEqual(d["frentes"],28)
        self.assertEqual(d["modelos_operacionais"],0)
        self.assertGreater(d["funcoes_vinculadas"],40)

    def test_meteo_hidro_cadeias_distintas_sem_duplicar_datasets(self):
        por_id={x["id"]:x for x in self.m["systems"]}
        self.assertIn("ANA_HIDRO",por_id["HIDROLOGIA"]["data"])
        self.assertIn("INMET_ESTACOES",por_id["METEOROLOGIA"]["data"])
        self.assertIn("INMET_ESTACOES",por_id["CLIMA_HIDRO"]["data"])

    def test_hidro_licenca_e_backfill_nao_viram_operacional(self):
        for x in self.r["engines"]:
            self.assertFalse(x["operational_enabled"])
            self.assertFalse(x["scheduled_enabled"])
            self.assertFalse(x["previsao_homologada"])

    def test_nao_aceita_modulo_forcado_pelo_manifesto(self):
        doc=copy.deepcopy(self.r)
        doc["engines"][0]["entrypoints"]=["os:system"]
        with self.assertRaises(ErroCatalogo):
            validar_registro(doc,self.m)

    def test_nao_aceita_modelo_nao_homologado_como_validado(self):
        doc=copy.deepcopy(self.r)
        doc["engines"][0]["previsao_homologada"]=True
        with self.assertRaises(ErroCatalogo):
            validar_registro(doc,self.m)

    def test_nao_aceita_frente_sem_motor(self):
        doc=copy.deepcopy(self.r)
        doc["engines"].pop()
        with self.assertRaises(ErroCatalogo):
            validar_registro(doc,self.m)

    def test_dataset_nao_equivale_calculo(self):
        doc=copy.deepcopy(self.r)
        doc["engines"][0]["data_dependencies"]=[]
        with self.assertRaises(ErroCatalogo):
            validar_registro(doc,self.m)


if __name__=="__main__":
    unittest.main()
