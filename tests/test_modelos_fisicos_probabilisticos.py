import unittest
from nivon.qualidade_cientifica import ErroCientifico
from nivon.modelos_fisicos import (eto_fao56_penman_monteith,avaliar_vazao_hidrologica,reconciliar_rebanho)
from nivon.verificacao_probabilistica import (brier_probabilidade,pontuacao_quantis,cobertura_intervalos)


class TestModelosFisicos(unittest.TestCase):
    def eto(self, **mod):
        par={"temperatura_media_c":20.0,"radiacao_liquida_mj_m2_dia":10.,
             "fluxo_calor_solo_mj_m2_dia":0.,"vento_2m_m_s":2.,
             "vapor_saturacao_kpa":2.34,"vapor_real_kpa":1.34,
             "declive_vapor_kpa_c":0.145,"constante_psicrometrica_kpa_c":0.0665,
             "referencia_fonte":"fixture FAO-56"}
        par.update(mod)
        return eto_fao56_penman_monteith(**par)

    def test_penman_monteith_formula(self):
        r=self.eto()
        numerador=0.408*0.145*10+0.0665*900/(20+273)*2*(2.34-1.34)
        esperado=numerador/(0.145+0.0665*(1+0.34*2))
        self.assertAlmostEqual(r["eto_mm_dia"],esperado)
        self.assertGreater(r["eto_mm_dia"],0)

    def test_penman_reject_vapor_invalid(self):
        with self.assertRaises(ErroCientifico):
            self.eto(vapor_real_kpa=3.)
        with self.assertRaises(ErroCientifico):
            self.eto(fluxo_calor_solo_mj_m2_dia=999.)
        with self.assertRaises(ErroCientifico):
            self.eto(vento_2m_m_s=-0.1)

    def test_hydro_perfect_scores(self):
        obs=[float(i) for i in range(1,21)]
        r=avaliar_vazao_hidrologica(observada_m3_s=obs,prevista_m3_s=obs,
                                    identificador_estacao="ANA-X",intervalo="diario")
        self.assertAlmostEqual(r["nse"],1)
        self.assertAlmostEqual(r["kge_2009"],1)
        self.assertAlmostEqual(r["vies_percentual_predito_menos_observado"],0)

    def test_hydro_pior_que_media(self):
        obs=[float(i) for i in range(1,21)]
        pred=[float(i*3) for i in range(1,21)]
        r=avaliar_vazao_hidrologica(observada_m3_s=obs,prevista_m3_s=pred,
                                    identificador_estacao="ANA-X",intervalo="diario")
        self.assertLess(r["nse"],0)
        self.assertLess(r["kge_2009"],1)

    def test_hydro_const_series_bloqueada(self):
        with self.assertRaises(ErroCientifico):
            avaliar_vazao_hidrologica(observada_m3_s=[10.]*11,prevista_m3_s=[10.]*11,
                                      identificador_estacao="ANA-X",intervalo="diario")

    def test_rebanho_conserva_identidade_e_rejeita_buraco(self):
        r=reconciliar_rebanho(especie="BOVINO",categoria="MATRIZES",
            estoque_inicial_cabecas=100,nascimentos_cabecas=10,compras_cabecas=2,
            transferencias_entrada_cabecas=0,mortes_cabecas=1,vendas_cabecas=4,
            abate_cabecas=2,transferencias_saida_cabecas=5,
            estoque_final_reportado_cabecas=100)
        self.assertTrue(r["consistente"])
        with self.assertRaises(ErroCientifico):
            reconciliar_rebanho(especie="BOVINO",categoria="MATRIZES",
              estoque_inicial_cabecas=1,nascimentos_cabecas=0,compras_cabecas=0,
              transferencias_entrada_cabecas=0,mortes_cabecas=0,vendas_cabecas=2,
              abate_cabecas=0,transferencias_saida_cabecas=0,
              estoque_final_reportado_cabecas=0)


class TestProbabilidade(unittest.TestCase):
    def test_brier_perfeito_e_benchmark(self):
        ocorrencias=[0,1]*5
        self.assertEqual(brier_probabilidade(probabilidades=ocorrencias,ocorrencias=ocorrencias,evento_definido="chuva > 20mm")["brier"],0)
        self.assertAlmostEqual(brier_probabilidade(probabilidades=[.5]*10,ocorrencias=ocorrencias,evento_definido="chuva > 20mm")["brier"],.25)
        with self.assertRaises(ErroCientifico):
            brier_probabilidade(probabilidades=[1.1]*10,ocorrencias=ocorrencias,evento_definido="chuva > 20mm")

    def test_pinball_e_cruzamento(self):
        obs=[100.]*10
        q=pontuacao_quantis(observados=obs,quantis=[.1,.5,.9],estimativas=[[90.,100.,110.]]*10,unidade="R$/t")
        self.assertAlmostEqual(q["pinball_medio"],2/3)
        with self.assertRaises(ErroCientifico):
            pontuacao_quantis(observados=obs,quantis=[.1,.5,.9],estimativas=[[110.,100.,90.]]*10,unidade="R$/t")

    def test_intervalo_cobertura(self):
        result=cobertura_intervalos(observados=[5.]*10,limites_inferiores=[4.]*10,
            limites_superiores=[6.]*10,nivel_nominal=.8,unidade="mm")
        self.assertEqual(result["cobertura_empirica"],1.)
        self.assertAlmostEqual(result["amplitude_media"],2.)
        with self.assertRaises(ErroCientifico):
            cobertura_intervalos(observados=[5.]*10,limites_inferiores=[6.]*10,
                limites_superiores=[4.]*10,nivel_nominal=.8,unidade="mm")


if __name__ == "__main__":
    unittest.main()
