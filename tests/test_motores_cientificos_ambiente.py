import unittest
from nivon.motores_agrometeorologia_fao56 import (
    ErroAgrometeo,pressao_saturacao_kpa,et0_fao56_diaria,
    deficit_hidrico_fenologico,diagnosticar_chuva_climatologica,
)
from nivon.motores_hidrologia_cientifica import (
    ErroHidrologia,curva_chave_interpolada,
    balanco_reservatorio_diario,avaliar_previsao_vazao,
)

def referencia_et0(**override):
    d=dict(tmin_c=19,tmax_c=31,umidade_min_pct=40,
           umidade_max_pct=85,vento_2m_ms=2,
           radiacao_liquida_mj_m2_dia=12,altitude_m=500,
           fonte_radiacao="Rn MJ/m2/dia hipotético",
           fonte_meteorologia="estacao fixture")
    d.update(override)
    return et0_fao56_diaria(**d)

class TestFAO56(unittest.TestCase):
    def test_pressao_vapor_20_graus(self):
        self.assertAlmostEqual(pressao_saturacao_kpa(20),2.338281,places=4)

    def test_fao56_consistencia_numerica(self):
        r=referencia_et0()
        self.assertAlmostEqual(r["et0_mm_dia"],5.0919337024,places=6)
        self.assertGreater(r["pressao_vapor_saturacao_kpa"],
                           r["pressao_vapor_real_kpa"])
        self.assertEqual(r["classificacao"],"ET0_MODELO_FISICO_FAO56")

    def test_fao56_sem_unidades_corretas_nao_homologa(self):
        for values in (
            {"umidade_min_pct":101},
            {"tmin_c":32},
            {"vento_2m_ms":70},
            {"radiacao_liquida_mj_m2_dia":500},
            {"tmin_c":float("nan")},
            {"tmax_c":True},
            {"fonte_radiacao":""},
            {"umidade_min_pct":95,"umidade_max_pct":20},
        ):
            with self.subTest(values=values),self.assertRaises(ErroAgrometeo):
                referencia_et0(**values)

    def test_et0_dia_sem_radiacao_relevante(self):
        r=referencia_et0(radiacao_liquida_mj_m2_dia=-10,
                         vento_2m_ms=0)
        self.assertEqual(r["et0_mm_dia"],0)
        self.assertTrue(r["clamp_zero_por_saldo_energetico"])

    def test_deficit_agua_balda_massa_fecha(self):
        v=deficit_hidrico_fenologico(et0_mm_dia=6,
            kc_cultura=1.1,chuva_efetiva_mm=3,
            armazenamento_inicial_mm=2,capacidade_disponivel_mm=30,
            fonte_solo_kc="Kc para cultivar hipotética",periodo="2026-10-20")
        self.assertAlmostEqual(v["et_cultura_potencial_mm"],6.6)
        self.assertAlmostEqual(v["et_atendida_mm"],5)
        self.assertAlmostEqual(v["deficit_et_mm"],1.6)
        self.assertEqual(v["armazenamento_final_mm"],0)

    def test_deficit_excesso_conserva(self):
        v=deficit_hidrico_fenologico(et0_mm_dia=5,kc_cultura=1.,
            chuva_efetiva_mm=70,armazenamento_inicial_mm=25,
            capacidade_disponivel_mm=40,fonte_solo_kc="fixture",
            periodo="2026-10-20")
        self.assertEqual(v["excedente_nao_especificado_mm"],50)
        self.assertEqual(v["armazenamento_final_mm"],40)

    def test_seca_percentil_exige_30_anos(self):
        ano=list(range(1991,2021))
        chuva=[20+i*5 for i in range(30)]
        x=diagnosticar_chuva_climatologica(chuva_acumulada_mm=100,
            climatologia_mes_mesma_janela_mm=120,
            amostras_anuais_referencia_mm=chuva,
            anos_referencia=ano,fonte="fixture 1991–2020")
        self.assertAlmostEqual(x["anomalia_percentual"],-16.6666666667)
        self.assertEqual(x["percentil_empirico"],55.0)  # 16 abaixo e 1 igual: mid-rank
        self.assertIn("NAO_SPI",x["classificacao"])
        with self.assertRaises(ErroAgrometeo):
            diagnosticar_chuva_climatologica(chuva_acumulada_mm=100,
                climatologia_mes_mesma_janela_mm=120,
                amostras_anuais_referencia_mm=chuva[:-1],
                anos_referencia=ano[:-1],fonte="fixture")

class TestHidrologiaCientifica(unittest.TestCase):
    def rating(self,**kw):
        d=dict(estacao_id="15400000",cota_cm=200,
               pares_aforos_cota_cm_vazao_m3s=[(100,10),(200,40),(300,160)],
               datum_referencia="régua ANA estação 15400000",
               versao_curva="CurvaTeste 2026-10",fonte_aforos="fixture ANA")
        d.update(kw)
        return curva_chave_interpolada(**d)

    def test_curva_chave_interpolacao_log_linear(self):
        x=self.rating(cota_cm=150)
        self.assertAlmostEqual(x["vazao_interpolada_m3_s"],20)
        self.assertEqual(x["intervalo_aforos_cm"],(100,200))
        self.assertFalse(x["aforo_exato"])
        self.assertAlmostEqual(self.rating()["vazao_interpolada_m3_s"],40)

    def test_curva_chave_proibe_extrapolacao(self):
        for v in (99,301):
            with self.assertRaises(ErroHidrologia):self.rating(cota_cm=v)
        with self.assertRaises(ErroHidrologia):
            self.rating(pares_aforos_cota_cm_vazao_m3s=[
                (100,10),(200,9),(300,160)])
        with self.assertRaises(ErroHidrologia):
            self.rating(pares_aforos_cota_cm_vazao_m3s=[
                (100,10),(100,20),(300,160)])

    def test_reservatorio_conserva_volume(self):
        x=balanco_reservatorio_diario(volume_inicial_m3=5_000_000,
            volume_maximo_m3=6_000_000,entrada_m3_s=10,
            saida_m3_s=5,precipitacao_mm=4,evaporacao_mm=2,
            area_lamina_km2=2,duracao_segundos=86400,
            fonte_metrica="fixture operacao")
        # (10-5)*86400 + (4-2)*2*1000 = 436,000 m3
        self.assertAlmostEqual(x["volume_final_m3"],5_436_000)
        self.assertEqual(x["vertimento_teorico_m3"],0)
        self.assertIn("DETERMINISTICO",x["classificacao"])

    def test_reservatorio_vertimento_explicito(self):
        x=balanco_reservatorio_diario(volume_inicial_m3=950_000,
            volume_maximo_m3=1_000_000,entrada_m3_s=5,saida_m3_s=0,
            precipitacao_mm=0,evaporacao_mm=0,area_lamina_km2=0,
            duracao_segundos=86400,fonte_metrica="fixture")
        self.assertEqual(x["volume_final_m3"],1_000_000)
        self.assertEqual(x["vertimento_teorico_m3"],382_000)

    def test_reservatorio_nega_retirada_impossivel(self):
        with self.assertRaises(ErroHidrologia):
            balanco_reservatorio_diario(volume_inicial_m3=1000,
                volume_maximo_m3=10000,entrada_m3_s=0,
                saida_m3_s=3,precipitacao_mm=0,evaporacao_mm=0,
                area_lamina_km2=0,duracao_segundos=86400,fonte_metrica="fixture")

    def test_nse_perfeito_e_baseline(self):
        obs=[float(i+10) for i in range(12)]
        prev=obs[:]
        base=[obs[0]]*12
        x=avaliar_previsao_vazao(observado_m3s=obs,
                previsto_m3s=prev,baseline_persistencia_m3s=base,
                fonte_observado="fixture observacao",fonte_previsao="fixture modelo")
        self.assertEqual(x["nse"],1)
        self.assertEqual(x["mae_m3_s"],0)
        self.assertEqual(x["skill_mse_contra_persistencia"],1)
        self.assertEqual(x["bias_m3_s"],0)

    def test_nse_amostra_pequena_nulo_negativo(self):
        with self.assertRaises(ErroHidrologia):
            avaliar_previsao_vazao(observado_m3s=[1,2],
                previsto_m3s=[1,2],baseline_persistencia_m3s=[1,1],
                fonte_observado="fixture",fonte_previsao="fixture")
        obs=[10]*12
        x=avaliar_previsao_vazao(observado_m3s=obs,previsto_m3s=obs,
            baseline_persistencia_m3s=obs,fonte_observado="fixture",
            fonte_previsao="fixture")
        self.assertIsNone(x["nse"])
        self.assertIsNone(x["skill_mse_contra_persistencia"])

if __name__=="__main__":
    unittest.main()
