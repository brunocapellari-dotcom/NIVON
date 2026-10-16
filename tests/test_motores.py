import math
import unittest

from nivon.motores import (
    CEPEA, ClasseDestino, DadoInvalido, FluxoANTT, classificar_destino,
    cobertura_ncm, estimar_milho_por_etanol, projetar_consumo,
    resumir_fluxos_mt, validar_fonte, verificar_teto_materia_seca,
)
from nivon.portos import PORTOS_BR, Programacao, contar_escalas


class TestConsumo(unittest.TestCase):
    def setUp(self):
        self.h = {2020: 78.0, 2021: 80.0, 2022: 76.8, 2023: 82.2}

    def test_cenario_principal_e_sensibilidade(self):
        res = projetar_consumo(self.h)
        self.assertEqual(res["classificacao"], "PROJETADO_CENARIO")
        self.assertAlmostEqual(res["projecoes"][1]["cenario_principal"], 85.1204, places=2)
        self.assertAlmostEqual(res["projecoes"][1]["sensibilidade_ultima_taxa"], 94.17, places=2)

    def test_lacuna_falha(self):
        with self.assertRaises(DadoInvalido):
            projetar_consumo({2020: 78, 2021: 80, 2023: 82, 2024: 83})

    def test_nulo_falha(self):
        with self.assertRaises(DadoInvalido):
            projetar_consumo({2020: 78, 2021: 80, 2022: None, 2023: 82})

    def test_horizonte_limitado(self):
        with self.assertRaises(DadoInvalido):
            projetar_consumo(self.h, horizonte=3)


class TestIndustria(unittest.TestCase):
    def test_cepea_margem_e_unidades_originais(self):
        self.assertEqual((CEPEA.etanol_l_por_t, CEPEA.ddg_kg_por_t, CEPEA.oleo_l_por_t), (440, 331, 20.4))
        self.assertIn("MARGEM", CEPEA.finalidade)
        self.assertEqual(CEPEA.tipo_etanol, "NAO_ESPECIFICADO")

    def test_cepea_suspeito_de_massa(self):
        for tipo in ("ANIDRO", "HIDRATADO"):
            x = verificar_teto_materia_seca(umidade_milho=.14, umidade_ddg=.11, tipo_etanol=tipo)
            self.assertEqual(x["status"], "SUSPEITO_BALANCO")
            self.assertGreater(x["excesso_kg"], 0)

    def test_tipo_etanol_obrigatorio(self):
        with self.assertRaises(DadoInvalido):
            verificar_teto_materia_seca(umidade_milho=.14, umidade_ddg=.11, tipo_etanol="INDEFINIDO")

    def test_milho_nao_identificavel_em_etanol_misto(self):
        with self.assertRaisesRegex(DadoInvalido, "NAO_IDENTIFICAVEL"):
            estimar_milho_por_etanol(litros_etanol=450000, rendimento_l_t=440,
                tipo_etanol="HIDRATADO", materia_prima="MISTO", fonte_rendimento="teste")

    def test_estimativa_exige_fonte_e_base(self):
        x = estimar_milho_por_etanol(litros_etanol=450000, rendimento_l_t=450,
            tipo_etanol="HIDRATADO", materia_prima="MILHO", fonte_rendimento="amostra sintética")
        self.assertEqual(x["milho_estimado_t"], 1000)
        self.assertEqual(x["classificacao"], "ESTIMADO")
        with self.assertRaises(DadoInvalido):
            estimar_milho_por_etanol(litros_etanol=450000, rendimento_l_t=450,
                tipo_etanol="HIDRATADO", materia_prima="MILHO", fonte_rendimento=None)


class TestFluxos(unittest.TestCase):
    def test_quatro_classes(self):
        self.assertEqual(classificar_destino(tem_terminal=True, tem_consumidor=True), ClasseDestino.AMBIGUO)
        self.assertEqual(classificar_destino(tem_terminal=True, tem_consumidor=False), ClasseDestino.TRANSBORDO_PROVAVEL)
        self.assertEqual(classificar_destino(tem_terminal=False, tem_consumidor=True), ClasseDestino.CONSUMO_POTENCIAL)
        self.assertEqual(classificar_destino(tem_terminal=False, tem_consumidor=False), ClasseDestino.SEM_EVIDENCIA)

    def test_preserva_ambiguidade_e_carga_propria(self):
        entradas = [
            FluxoANTT("MT", "GO", "RIO VERDE", "10059010", 100, True),
            FluxoANTT("MT", "SC", "CHAPECO", "12019000", 50, False),
            FluxoANTT("MT", "SP", "SANTOS", "10059010", 20, False),
            FluxoANTT("MT", "MT", "CUIABA", "10059010", 600, False),
            FluxoANTT("MT", "SC", "CHAPECO", "10051000", 5, False),
        ]
        r = resumir_fluxos_mt(entradas, {("GO", "RIO VERDE"), ("SP", "SANTOS")},
                            {("GO", "RIO VERDE"), ("SC", "CHAPECO")})
        self.assertEqual(r["total_identificado_t"], 170)
        self.assertEqual(r["por_classe_t"]["AMBIGUO"], 100)
        self.assertEqual(r["por_classe_t"]["CONSUMO_POTENCIAL"], 50)
        self.assertEqual(r["por_classe_t"]["TRANSBORDO_PROVAVEL"], 20)
        self.assertAlmostEqual(sum(r["por_classe_t"].values()), r["total_identificado_t"])
        self.assertTrue(r["ncm_nao_e_total"])

    def test_cobertura_de_amostra(self):
        self.assertEqual(cobertura_ncm(volume_total_painel_t=100, volume_com_ncm_t=32)["taxa_cobertura_ncm"], .32)
        with self.assertRaises(DadoInvalido):
            cobertura_ncm(volume_total_painel_t=100, volume_com_ncm_t=110)

    def test_ncm_deve_preservar_zeros(self):
        with self.assertRaises(DadoInvalido):
            FluxoANTT("MT", "GO", "RIO VERDE", "1005901", 1, True)

    def test_fonte_nao_habilitada(self):
        with self.assertRaises(PermissionError):
            validar_fonte(status="PENDENTE", operacao="COLETA", operacoes_autorizadas={"COLETA"})
        with self.assertRaises(PermissionError):
            validar_fonte(status="APROVADA", operacao="REDISTRIBUICAO", operacoes_autorizadas={"COLETA"})
        validar_fonte(status="APROVADA", operacao="COLETA", operacoes_autorizadas={"COLETA"})


class TestPortos(unittest.TestCase):
    def test_dez_portos(self):
        self.assertEqual(len(PORTOS_BR), 10)
        self.assertEqual(len(set(PORTOS_BR)), 10)

    def test_programado_nao_e_realizado(self):
        with self.assertRaises(ValueError):
            Programacao("SANTOS", "NAVIO A", "duv", None, "soja", 100, "fonte", "2026-10-16T00:00:00Z", "CONCLUIDO")

    def test_duv_deduplicado(self):
        def p(n, duv):
            return Programacao("SANTOS", n, duv, None, "soja", 100, "exemplo", "2026-10-16")
        r = contar_escalas([p("A", "1"), p("A", "1"), p("B", "2"), p("C", None)])
        self.assertEqual(r["escalas_distintas_identificadas"], 2)
        self.assertEqual(r["linhas_sem_identificador_confiavel"], 1)


if __name__ == "__main__":
    unittest.main()
