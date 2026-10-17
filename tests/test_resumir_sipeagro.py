import json
import unittest

from scripts.resumir_sipeagro import resumir


class TestResumoSIPEAGRO(unittest.TestCase):
    def cadastro(self):
        return (
            "UF;MUNICIPIO;NUMERO_REGISTRO_ESTABELECIMENTO;STATUS_DO_REGISTRO;"
            "AREA_ATUACAO;ATIVIDADE;CLASSIFICACAO;CPF_CNPJ;RAZAO_SOCIAL\n"
            "GO;Rio Verde;REG-001;Ativo;ALIMENTAÇÃO ANIMAL;FABRICANTE;RAÇÃO;X;FAKE COMPANY\n"
            "GO;Rio Verde;REG-001;Ativo;ALIMENTAÇÃO ANIMAL;FABRICANTE;RAÇÃO;X;FAKE COMPANY\n"
            "SC;Chapecó;REG-002;Ativo;ALIMENTAÇÃO ANIMAL;FABRICANTE;RAÇÃO;Y;ANOTHER FAKE\n"
            "SC;Chapecó;REG-003;Cancelado;ALIMENTAÇÃO ANIMAL;FABRICANTE;RAÇÃO;Z;FAKE\n"
            "PR;Cascavel;REG-004;Ativo;ALIMENTAÇÃO ANIMAL;IMPORTADOR;RAÇÃO;W;FAKE\n"
            "PR;Cascavel;REG-005;Ativo;ALIMENTAÇÃO ANIMAL;FABRICANTE;INGREDIENTE;W;FAKE\n"
        )

    def test_conta_municipios_e_deduplica_registros(self):
        r = resumir(self.cadastro().encode("utf-8"))
        self.assertEqual(r["linhas_do_arquivo"], 6)
        self.assertEqual(r["linhas_filtradas_fabricante_ativo_racao"], 3)
        self.assertEqual(r["registros_estabelecimento_distintos_com_identificador"], 2)
        self.assertEqual(r["municipios_distintos_com_fabricante_ativo_racao"], 2)
        self.assertEqual(r["municipios_por_uf"], {"GO": 1, "SC": 1})

    def test_nao_publica_campos_individuais(self):
        r = resumir(self.cadastro().encode("utf-8"))
        s = json.dumps(r, ensure_ascii=False)
        self.assertNotIn("FAKE COMPANY", s)
        self.assertNotIn("REG-001", s)
        self.assertNotIn("CPF_CNPJ", s)

    def test_exportacao_aggregada_so_municipio(self):
        r = resumir(self.cadastro().encode("utf-8"), incluir_municipios=True)
        self.assertEqual(len(r["municipios_candidatos"]), 2)
        s = json.dumps(r, ensure_ascii=False)
        self.assertNotIn("FAKE COMPANY", s)
        self.assertNotIn("REG-001", s)

    def test_por_padrao_nao_imprime_lista_completa(self):
        r = resumir(self.cadastro().encode("utf-8"))
        self.assertNotIn("municipios_candidatos", r)

    def test_schema_incompativel_bloqueado(self):
        with self.assertRaises(ValueError):
            resumir(b"UF;MUNICIPIO\nGO;Rio Verde\n")

    def test_status_cancelado_nao_incluido(self):
        r = resumir(self.cadastro().encode("utf-8"))
        self.assertEqual(len(r["municipios_com_mais_registros_top_25"]), 2)


if __name__ == "__main__":
    unittest.main()
