import unittest

from nivon.destinos import (
    ErroFluxo, FabricaMAPA, FluxoMensal, Terminal, analisar_destinos,
    chave_municipio, mes_referencia, normalizar_municipio,
)


class TestDestinosANTTMAPA(unittest.TestCase):
    def fabrica(self, cidade="Rio Verde", uf="GO", *, ativa=True, fabricante=True):
        return FabricaMAPA(uf, cidade, fabricante, ativa, True, "SIPEAGRO_TESTE", "RAÇÃO")

    def terminal(self, cidade="Rio Verde", uf="GO", produtos=frozenset({"MILHO"})):
        return Terminal(uf, cidade, "FERROVIARIO", produtos, "TERMINAL_TESTE")

    def fluxo(self, periodo="2026-01", cidade="Rio Verde", uf="GO", *,
              ncm="10059010", toneladas=50, propria=False):
        return FluxoMensal(periodo, "MT", "Lucas do Rio Verde", uf, cidade,
                          ncm, toneladas, propria, "ANTT_TESTE")

    def analisar(self, fluxos, fabricas=(), terminais=(), *, mes_corte="2026-04"):
        return analisar_destinos(fluxos, fabricas, terminais, mes_corte=mes_corte)

    def test_normaliza_acentos_sem_colidir_uf(self):
        self.assertEqual(normalizar_municipio("  São  Francisco  do Sul "), "SAO FRANCISCO DO SUL")
        self.assertNotEqual(chave_municipio("SC", "Rio do Sul"), chave_municipio("RS", "Rio do Sul"))

    def test_meses_validacao(self):
        with self.assertRaises(ErroFluxo):
            mes_referencia("2026-13")

    def test_fabrica_e_terminal_ambiguidade_preservada(self):
        r = self.analisar([self.fluxo()], [self.fabrica()], [self.terminal()])
        self.assertEqual(r["total_t_identificado"], 50)
        self.assertEqual(r["destinos"][0]["classe"], "AMBIGUO")
        self.assertTrue(r["nao_equivale_consumo_final"])

    def test_fabrica_sem_terminal_consumo_so_potencial(self):
        r = self.analisar([self.fluxo()], [self.fabrica()])
        self.assertEqual(r["destinos"][0]["classe"], "CONSUMO_POTENCIAL")

    def test_fabrica_inativa_ou_nao_fabricante_excluida(self):
        r = self.analisar([self.fluxo()], [self.fabrica(ativa=False)])
        self.assertEqual(r["destinos"][0]["classe"], "SEM_EVIDENCIA")
        r = self.analisar([self.fluxo()], [self.fabrica(fabricante=False)])
        self.assertEqual(r["destinos"][0]["classe"], "SEM_EVIDENCIA")

    def test_terminal_de_outro_produto_nao_classifica(self):
        r = self.analisar([self.fluxo()], [], [self.terminal(produtos=frozenset({"SOJA"}))])
        self.assertEqual(r["destinos"][0]["classe"], "SEM_EVIDENCIA")

    def test_fabricante_ingrediente_nao_equivale_fabrica_racao(self):
        fabricante = FabricaMAPA("GO", "Rio Verde", True, True, True, "TESTE", "INGREDIENTE")
        r = self.analisar([self.fluxo()], [fabricante])
        self.assertEqual(r["destinos"][0]["classe"], "SEM_EVIDENCIA")

    def test_terminal_sem_fabrica_transbordo_provavel(self):
        r = self.analisar([self.fluxo()], [], [self.terminal()])
        self.assertEqual(r["destinos"][0]["classe"], "TRANSBORDO_PROVAVEL")

    def test_carga_propria_nao_excluida_e_volume_conservado(self):
        r = self.analisar([self.fluxo(propria=True, toneladas=70), self.fluxo(toneladas=30)])
        self.assertEqual(r["total_t_identificado"], 100)
        self.assertEqual(r["destinos"][0]["toneladas_carga_propria"], 70)
        self.assertEqual(r["destinos"][0]["toneladas_terceiros"], 30)

    def test_recorrencia_3_meses_distintos_nao_numero_de_linhas(self):
        entradas = [self.fluxo(periodo="2026-01"), self.fluxo(periodo="2026-01", propria=True),
                    self.fluxo(periodo="2026-02"), self.fluxo(periodo="2026-03")]
        r = self.analisar(entradas)
        self.assertTrue(r["destinos"][0]["recorrente"])
        self.assertEqual(r["destinos"][0]["meses_com_fluxo"], 3)

    def test_recorrencia_nao_confunde_dois_meses_com_tres_viagens(self):
        entradas = [self.fluxo(periodo="2026-01"), self.fluxo(periodo="2026-01", propria=True),
                    self.fluxo(periodo="2026-02")]
        self.assertFalse(self.analisar(entradas)["destinos"][0]["recorrente"])

    def test_mesmo_recorte_mensal_duplicado_e_erro(self):
        with self.assertRaises(ErroFluxo):
            self.analisar([self.fluxo(), self.fluxo()])

    def test_periodo_fora_da_janela_ignorado(self):
        r = self.analisar([self.fluxo(periodo="2024-01"), self.fluxo(periodo="2026-04")])
        self.assertEqual(r["total_t_identificado"], 50)

    def test_ncm_desconhecido_nao_inventado(self):
        r = self.analisar([self.fluxo(ncm="12010000"), self.fluxo()])
        self.assertEqual(r["linhas_ncm_outros"], 1)
        self.assertEqual(r["total_t_identificado"], 50)
        self.assertIsNone(r["taxa_cobertura_ncm"])

    def test_uf_mt_excluida_por_definicao_interestadual(self):
        r = self.analisar([self.fluxo(cidade="Cuiaba", uf="MT")])
        self.assertEqual(r["destinos"], [])

    def test_entrada_negativa_rejeitada(self):
        with self.assertRaises(ErroFluxo):
            self.fluxo(toneladas=-10)

    def test_terminal_sem_fonte_rejeitado(self):
        with self.assertRaises(ErroFluxo):
            Terminal("GO", "Rio Verde", "FERROVIARIO", frozenset({"MILHO"}), "")


if __name__ == "__main__":
    unittest.main()
