"""Regression tests: PAM 1612 crop/variable/unit semantics must stay aligned."""
import unittest
from nivon.ivo_pam_semantica import (
    conferir_semantica_pam_1612,ErroSemanticaPAM,GRANDEZAS_1612,
    PRODUTOS_VERIFICADOS,
)

class TestIVOSemanticaPAM(unittest.TestCase):
    def test_soja_producao_toneladas(self):
        d=conferir_semantica_pam_1612(
            variavel="214",categoria_c81="2713",unidade="Toneladas",
            indicador_esperado="QUANTIDADE_PRODUZIDA")
        self.assertEqual(d["produto"],"SOJA_EM_GRAO")
        self.assertEqual(d["familia"],"MASSA")
        self.assertFalse(d["rotulo_real_certificado"])

    def test_soja_area_hectares(self):
        d=conferir_semantica_pam_1612(
            variavel="109",categoria_c81="2713",unidade="Hectares")
        self.assertEqual(d["indicador"],"AREA_PLANTADA")
        self.assertEqual(d["familia"],"AREA")

    def test_arroz_nao_e_soja(self):
        d=conferir_semantica_pam_1612(
            variavel="214",categoria_c81="2692",unidade="Toneladas")
        self.assertEqual(d["produto"],"ARROZ_EM_CASCA")
        self.assertNotEqual(d["produto"],"SOJA_EM_GRAO")

    def test_sorgo_milho_nao_se_confundem(self):
        sorgo=conferir_semantica_pam_1612(
            variavel="214",categoria_c81="2714",unidade="Toneladas")
        milho=conferir_semantica_pam_1612(
            variavel="214",categoria_c81="2711",unidade="Toneladas")
        self.assertNotEqual(sorgo["produto"],milho["produto"])

    def test_area_nao_pode_ser_tratada_como_volume(self):
        for code,unit in (("109","Toneladas"),("214","Hectares"),
                          ("109","Quilogramas"),("214","kg")):
            with self.subTest(code=code,unit=unit):
                with self.assertRaises(ErroSemanticaPAM):
                    conferir_semantica_pam_1612(
                        variavel=code,categoria_c81="2713",unidade=unit)

    def test_indicador_declarado_divergente_bloqueado(self):
        with self.assertRaises(ErroSemanticaPAM):
            conferir_semantica_pam_1612(
                variavel="109",categoria_c81="2713",unidade="Hectares",
                indicador_esperado="QUANTIDADE_PRODUZIDA")

    def test_variavel_desconhecida_nao_infere_unidade(self):
        for code in ("112","999","",None,109):
            with self.subTest(code=code):
                with self.assertRaises(ErroSemanticaPAM):
                    conferir_semantica_pam_1612(
                        variavel=code,categoria_c81="2713",unidade="Toneladas")

    def test_produto_desconhecido_exige_novo_catalogo_auditado(self):
        for code in ("0000","",None,2713):
            with self.subTest(code=code):
                with self.assertRaises(ErroSemanticaPAM):
                    conferir_semantica_pam_1612(
                        variavel="214",categoria_c81=code,unidade="Toneladas")

    def test_mapeamentos_sem_codigos_duplicados(self):
        self.assertEqual(len(GRANDEZAS_1612),len(set(GRANDEZAS_1612)))
        self.assertEqual(len(PRODUTOS_VERIFICADOS),len(set(PRODUTOS_VERIFICADOS)))

if __name__=="__main__":
    unittest.main()
