import copy
import unittest
from scripts.validar_agregado import ErroPublicacao, validar


class TestAgregadoPublicavel(unittest.TestCase):
    def base(self):
        return {
            "fonte": "MAPA SIPEAGRO ALIMENTAÇÃO ANIMAL",
            "licenca_catalogo": "Creative Commons Attribution",
            "municipios_distintos_com_fabricante_ativo_racao": 2,
            "municipios_candidatos": [
                {"uf": "GO", "municipio": "RIO VERDE", "registros_distintos": 2},
                {"uf": "MT", "municipio": "SORRISO", "registros_distintos": 1},
            ],
            "natureza": "CADASTRO_OFICIAL_OBSERVADO_NAO_CONSUMO",
        }

    def test_agregado_valido(self):
        self.assertTrue(validar(self.base())["publicavel"])

    def test_identificador_vaza_e_bloqueado(self):
        d = self.base()
        d["CPF_CNPJ"] = "12345678900"
        with self.assertRaises(ErroPublicacao):
            validar(d)

    def test_entrada_individual_extra_e_bloqueada(self):
        d = self.base()
        d["municipios_candidatos"][0]["razao"] = "EMPRESA"
        with self.assertRaises(ErroPublicacao):
            validar(d)

    def test_contagem_inconsistente_e_bloqueada(self):
        d = self.base()
        d["municipios_distintos_com_fabricante_ativo_racao"] = 3
        with self.assertRaises(ErroPublicacao):
            validar(d)

    def test_municipio_repetido_e_bloqueado(self):
        d = self.base()
        d["municipios_candidatos"].append(copy.deepcopy(d["municipios_candidatos"][0]))
        d["municipios_distintos_com_fabricante_ativo_racao"] = 3
        with self.assertRaises(ErroPublicacao):
            validar(d)


if __name__ == "__main__":
    unittest.main()
