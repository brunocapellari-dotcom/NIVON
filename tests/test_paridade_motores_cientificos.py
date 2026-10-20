"""Concordância matemática entre implementações cientificamente equivalentes."""
import unittest
from nivon.motores_agrometeorologia_fao56 import et0_fao56_diaria
from nivon.modelos_fisicos import eto_fao56_penman_monteith,avaliar_vazao_hidrologica
from nivon.motores_hidrologia_cientifica import avaliar_previsao_vazao


class TestParidadeCientifica(unittest.TestCase):
    def test_fao56_meteorologia_vs_termos_reduzidos(self):
        a=et0_fao56_diaria(
            tmin_c=20,tmax_c=30,umidade_min_pct=45,umidade_max_pct=85,
            vento_2m_ms=2.5,radiacao_liquida_mj_m2_dia=14,
            altitude_m=250,fluxo_calor_solo_mj_m2_dia=0.,
            fonte_radiacao="NASA / QC",fonte_meteorologia="INMET / QC")
        b=eto_fao56_penman_monteith(
            temperatura_media_c=25,radiacao_liquida_mj_m2_dia=14.,
            fluxo_calor_solo_mj_m2_dia=0.,vento_2m_m_s=2.5,
            vapor_saturacao_kpa=a["pressao_vapor_saturacao_kpa"],
            vapor_real_kpa=a["pressao_vapor_real_kpa"],
            declive_vapor_kpa_c=a["delta_kpa_c"],
            constante_psicrometrica_kpa_c=a["gamma_kpa_c"],
            referencia_fonte="mesmos insumos FAO-56")
        self.assertAlmostEqual(a["et0_mm_dia"],b["eto_mm_dia"],places=11)

    def test_nse_mesma_definicao_independente(self):
        observado=[float(i) for i in range(5,25)]
        previsto=[v+(1 if i%2 else -1) for i,v in enumerate(observado)]
        base=[observado[0] for _ in observado]
        a=avaliar_previsao_vazao(
            observado_m3s=observado,previsto_m3s=previsto,
            baseline_persistencia_m3s=base,
            fonte_observado="ANA / TESTE",fonte_previsao="NIVON / TESTE")
        b=avaliar_vazao_hidrologica(
            observada_m3_s=observado,prevista_m3_s=previsto,
            identificador_estacao="ANA TESTE",intervalo="diario")
        self.assertAlmostEqual(a["nse"],b["nse"],places=12)
        self.assertEqual(a["n"],b["pares"])

if __name__=="__main__":unittest.main()
