import unittest
from dataclasses import replace

from nivon.balancos import (
    Balanco, ParcelaConsumo, Proveniencia, conferir_consistencia_componentes,
    decompor_consumo, reconciliar_balanco,
)
from nivon.motores import DadoInvalido


class TestBalancos(unittest.TestCase):
    def setUp(self):
        self.p = Proveniencia("FONTE_SINTETICA", "ESTIMADO", "2025", "2025-12-31",
                             "2026-01-10", "2026-01-11T12:00:00Z", "ANO_CIVIL")

    def test_balanco_brasil_fechado(self):
        b = self.base()
        r = reconciliar_balanco(b)
        self.assertTrue(r["conciliado"])
        self.assertEqual(r["oferta_t"], 150)
        self.assertEqual(r["destinacao_t"], 150)
        self.assertEqual(r["status"], "FECHADO")

    def base(self):
        return Balanco(
            produto="MILHO", escopo="BRASIL", calendario="ANO_CIVIL",
            competencia="2025", estoque_inicial_t=10, producao_t=140,
            importacao_t=0, entradas_interestaduais_t=0, consumo_domestico_t=95,
            exportacao_t=40, saidas_interestaduais_t=0, perdas_t=5,
            estoque_final_t=10, proveniencia=self.p
        )

    def test_balanco_diferenca_nao_e_escondida(self):
        b = replace(self.base(), exportacao_t=42)
        r = reconciliar_balanco(b)
        self.assertFalse(r["conciliado"])
        self.assertEqual(r["diferenca_t"], -2)
        self.assertEqual(r["status"], "DIVERGENTE")

    def test_brasil_nao_aceita_fluxos_entre_ufs(self):
        with self.assertRaises(DadoInvalido):
            replace(self.base(), entradas_interestaduais_t=10)

    def test_uf_aceita_entradas_e_saidas_interestaduais(self):
        b = replace(self.base(), escopo="UF", entradas_interestaduais_t=5,
                    saidas_interestaduais_t=5)
        self.assertTrue(reconciliar_balanco(b)["conciliado"])

    def test_falta_insumo_essencial_falha(self):
        with self.assertRaises(DadoInvalido):
            replace(self.base(), estoque_final_t=None)

    def test_consumo_decomposto_sem_duplicar(self):
        dados = decompor_consumo(
            total_t=95, parcelas=(
                ParcelaConsumo("RACAO", 55, self.p),
                ParcelaConsumo("ETANOL_MILHO", 20, self.p),
            ), calendario="ANO_CIVIL", competencia="2025"
        )
        self.assertEqual(dados["outros_usos_residuais_t"], 20)
        conferir_consistencia_componentes(self.base(), dados)

    def test_componentes_acima_do_total_falha(self):
        with self.assertRaisesRegex(DadoInvalido, "DUPLA_CONTAGEM"):
            decompor_consumo(total_t=95, parcelas=(
                ParcelaConsumo("RACAO", 85, self.p),
                ParcelaConsumo("ETANOL", 30, self.p),
            ), calendario="ANO_CIVIL", competencia="2025")

    def test_categoria_duplicada_falha(self):
        with self.assertRaises(DadoInvalido):
            decompor_consumo(total_t=95, parcelas=(
                ParcelaConsumo("RACAO", 10, self.p),
                ParcelaConsumo("RACAO", 12, self.p)
            ), calendario="ANO_CIVIL", competencia="2025")

    def test_ano_civil_nao_se_mistura_a_safra(self):
        safra = replace(self.p, calendario="SAFRA")
        with self.assertRaises(DadoInvalido):
            decompor_consumo(total_t=95,
                              parcelas=(ParcelaConsumo("RACAO", 10, safra),),
                              calendario="ANO_CIVIL", competencia="2025")
        with self.assertRaises(DadoInvalido):
            replace(self.base(), calendario="SAFRA")

    def test_competencia_nao_mistura(self):
        com_ano_diferente = replace(self.p, competencia="2024")
        with self.assertRaises(DadoInvalido):
            decompor_consumo(total_t=95,
                              parcelas=(ParcelaConsumo("RACAO", 10, com_ano_diferente),),
                              calendario="ANO_CIVIL", competencia="2025")

    def test_verifica_total_decomposto(self):
        with self.assertRaises(DadoInvalido):
            conferir_consistencia_componentes(
                self.base(), {"calendario": "ANO_CIVIL", "competencia": "2025",
                              "consumo_total_t": 94}
            )


if __name__ == "__main__":
    unittest.main()
