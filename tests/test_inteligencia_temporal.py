import unittest
from datetime import date

from nivon.motores import DadoInvalido
from nivon.inteligencia_temporal import (
    decompor_mudanca_safra,decompor_variacao_preco,comparar_progresso_safra,
    concentracao_fluxos,benchmark_sazonal_mensal,custo_diesel_por_rota,
)


class TestInteligenciaTemporal(unittest.TestCase):
    def test_mudanca_safra_conciliada_em_area_produtividade(self):
        for produto in ("SOJA","MILHO","ALGODAO","TRIGO","SORGO","CANA","GERGELIM"):
            x=decompor_mudanca_safra(produto=produto,area_anterior_ha=100,
                area_atual_ha=110,rendimento_anterior_kg_ha=3000,
                rendimento_atual_kg_ha=3100,fonte_metodologia="fixture")
            self.assertEqual(x["producao_anterior_t"],300)
            self.assertEqual(x["producao_atual_t"],341)
            self.assertAlmostEqual(x["efeito_area_contabil_t"],30.5)
            self.assertAlmostEqual(x["efeito_produtividade_contabil_t"],10.5)
            self.assertAlmostEqual(x["efeito_area_contabil_t"]+x["efeito_produtividade_contabil_t"],x["variacao_producao_t"])

    def test_cambio_e_preco_decomposicao_exata(self):
        x=decompor_variacao_preco(preco_usd_t_anterior=100,
            preco_usd_t_atual=120,cambio_anterior_rs_usd=5,
            cambio_atual_rs_usd=6,fonte_preco="fixture",fonte_cambio="fixture")
        self.assertEqual(x["variacao_total_rs_t"],220)
        self.assertEqual(x["efeito_cambio_contabil_rs_t"],110)
        self.assertEqual(x["efeito_preco_externo_contabil_rs_t"],110)
        with self.assertRaises(DadoInvalido):
            decompor_variacao_preco(preco_usd_t_anterior=100,
                preco_usd_t_atual=120,cambio_anterior_rs_usd=0,
                cambio_atual_rs_usd=6,fonte_preco="fixture",fonte_cambio="fixture")

    def test_progresso_plantio_colheita_mesma_semana(self):
        x=comparar_progresso_safra(percentual_atual=30,percentual_ano_passado=40,
             percentual_media_historica=45,produto="SOJA",regiao="MT",
             semana_referencia="2026-W42",fonte="CONAB fixture")
        self.assertEqual(x["desvio_ano_passado_pontos_percentuais"],-10)
        self.assertEqual(x["desvio_media_pontos_percentuais"],-15)
        with self.assertRaises(DadoInvalido):
            comparar_progresso_safra(percentual_atual=130,percentual_ano_passado=40,
                 percentual_media_historica=45,produto="SOJA",regiao="MT",
                 semana_referencia="2026-W42",fonte="fixture")

    def test_concentracao_destinos_sem_escore_de_risco_inferido(self):
        x=concentracao_fluxos(volumes_por_destino_t={"CHINA":60,"OUTROS":40},fonte="MDIC fixture")
        self.assertAlmostEqual(x["indice_hhi_fracao"],.52)
        self.assertEqual(x["maior_destino"],"CHINA")
        self.assertNotIn("probabilidade",x)
        with self.assertRaises(DadoInvalido):
            concentracao_fluxos(volumes_por_destino_t={"CHINA":0},fonte="MDIC fixture")

    def test_sazonalidade_walkforward_sem_olhar_futuro(self):
        ser={}
        for ano in range(2023,2026):
            for mes in range(1,13):
                ser[f"{ano}-{mes:02d}"]=100+mes*10
        x=benchmark_sazonal_mensal(serie_mensal=ser,fonte="fixture",competencia_as_of="2025-12")
        self.assertEqual(x["folds"],24)
        self.assertEqual(x["mae_sazonal"],0)
        self.assertFalse(x["modelo_preditivo_homologado"])
        with self.assertRaises(DadoInvalido):
            benchmark_sazonal_mensal(serie_mensal=ser,fonte="fixture",competencia_as_of="2025-11")
        ser.pop("2024-06")
        with self.assertRaises(DadoInvalido):
            benchmark_sazonal_mensal(serie_mensal=ser,fonte="fixture",competencia_as_of="2025-12")

    def test_custo_diesel_uso_ida_volta(self):
        x=custo_diesel_por_rota(distancia_ida_km=500,distancia_volta_km=500,
              consumo_l_km_ida=.5,consumo_l_km_volta=.4,
              diesel_b_rs_l=5,carga_util_t=30,fonte="fixture")
        self.assertEqual(x["consumo_total_estimado_l"],450)
        self.assertEqual(x["custo_diesel_viagem_rs"],2250)
        self.assertEqual(x["custo_diesel_rs_t_transportada"],75)
        self.assertIn("CENARIO",x["classificacao"])


if __name__=="__main__":
    unittest.main()
