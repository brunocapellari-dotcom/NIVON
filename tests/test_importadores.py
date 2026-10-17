import unittest

from nivon.importadores import ErroMapeamento, decimal_ptbr, mapear_fabricas, mapear_fluxos


MAPA = {"uf": "estado", "municipio": "cidade", "situacao": "status",
        "atividade": "atividade", "area": "categoria", "classificacao": "classe"}
ANTT = {"periodo": "mes", "origem_uf": "uf_inicio", "origem_municipio": "origem",
        "destino_uf": "uf_fim", "destino_municipio": "destino", "ncm": "codigo",
        "toneladas": "carga_t", "carga_propria": "propria"}


class TestImportadores(unittest.TestCase):
    def fabrica(self, **alteracoes):
        dados = {"estado": "GO", "cidade": "Rio Verde", "status": "Ativo",
                 "atividade": "Fabricante", "categoria": "Alimentação Animal", "classe": "Ração"}
        dados.update(alteracoes)
        return dados

    def fab(self, linhas):
        return mapear_fabricas(linhas, MAPA, fonte_id="FONTE_SINTETICA",
                              situacoes_ativas=frozenset({"ATIVO"}),
                              situacoes_inativas=frozenset({"INATIVO"}),
                              atividades_fabricante=frozenset({"FABRICANTE"}),
                              atividades_nao_fabricante=frozenset({"IMPORTADOR"}),
                              areas_alimentacao_animal=frozenset({"ALIMENTACAO ANIMAL"}),
                              areas_nao_alimentacao_animal=frozenset({"FERTILIZANTE"}))

    def linha(self, **alteracoes):
        dados = {"mes": "2026-04", "uf_inicio": "MT", "origem": "Sorriso",
                 "uf_fim": "GO", "destino": "Rio Verde", "codigo": "10059010",
                 "carga_t": "1.234,50", "propria": "S"}
        dados.update(alteracoes)
        return dados

    def test_fabrica_ativa_fabricante(self):
        self.assertTrue(self.fab([self.fabrica()])[0].racao_registrada)

    def test_cadastro_inativo_nao_e_fabrica_ativa(self):
        self.assertFalse(self.fab([self.fabrica(status="Inativo")])[0].elegivel)

    def test_status_desconhecido_rejeita(self):
        with self.assertRaises(ErroMapeamento):
            self.fab([self.fabrica(status="Talvez")])

    def test_mapeamento_obrigatorio(self):
        with self.assertRaises(ErroMapeamento):
            mapear_fabricas([self.fabrica()], {"uf": "estado"},
                            fonte_id="X", situacoes_ativas=frozenset({"ATIVO"}),
                            situacoes_inativas=frozenset({"INATIVO"}),
                            atividades_fabricante=frozenset({"FABRICANTE"}),
                            atividades_nao_fabricante=frozenset({"IMPORTADOR"}),
                            areas_alimentacao_animal=frozenset({"ALIMENTACAO ANIMAL"}),
                            areas_nao_alimentacao_animal=frozenset({"FERTILIZANTE"}))

    def test_decimal_ptbr_explicito(self):
        self.assertEqual(decimal_ptbr("1.234,50"), 1234.5)
        self.assertEqual(decimal_ptbr("150,00"), 150)
        with self.assertRaises(ErroMapeamento):
            decimal_ptbr("1,234.50")

    def test_antt_so_produtos_definidos_sem_silent_conversion(self):
        a = mapear_fluxos([self.linha()], ANTT, fonte_id="ANTT_TESTE")
        self.assertEqual(a["fluxos"][0].toneladas, 1234.5)
        self.assertTrue(a["fluxos"][0].carga_propria)
        self.assertEqual(a["linhas_ncm_ausente"], 0)

    def test_ncm_ausente_separa_massa_sem_atribuir_produto(self):
        a = mapear_fluxos([self.linha(codigo=None, carga_t="200,25")],
                          ANTT, fonte_id="ANTT_TESTE")
        self.assertEqual(a["fluxos"], [])
        self.assertEqual(a["linhas_ncm_ausente"], 1)
        self.assertEqual(a["toneladas_sem_ncm_t"], 200.25)

    def test_outro_ncm_nao_virou_soja(self):
        a = mapear_fluxos([self.linha(codigo="10051000")], ANTT, fonte_id="ANTT_TESTE")
        self.assertEqual(a["fluxos"], [])
        self.assertEqual(a["linhas_outros_produtos"], 1)

    def test_carga_propria_terceiros(self):
        a = mapear_fluxos([self.linha(propria="N")], ANTT, fonte_id="ANTT_TESTE")
        self.assertFalse(a["fluxos"][0].carga_propria)

    def test_carga_com_codigo_invalido_rejeita(self):
        with self.assertRaises(ErroMapeamento):
            mapear_fluxos([self.linha(propria="desconhecido")], ANTT, fonte_id="ANTT_TESTE")


if __name__ == "__main__":
    unittest.main()
