import unittest
from datetime import datetime,timedelta,timezone
from nivon.hidrograma_bacia import hidrograma_evento_cn,ErroHidrograma
from nivon.hidrologia_chuva_vazao import escoamento_scs_cn

def rain(values,step=1):
    start=datetime(2025,2,1,tzinfo=timezone.utc)
    return [{"data_hora":(start+timedelta(hours=i*step)).isoformat(),
             "chuva_area_mm":v} for i,v in enumerate(values)]

def basin(**kwargs):
    defaults=dict(chuva_intervalos=rain([0.,30.,50.,20.,0.]),
         passo_horas=1,numero_curva=80,area_bacia_km2=120,
         fracao_abstracao_inicial=.2,
         resposta_unitaria_pesos=[.25,.5,.25],
         fonte_chuva="CHIRPS 3 grade area hypotetica",
         fonte_cn="CN80 fixture solo e cobertura",
         fonte_resposta_unitaria="kernel experimental, nao calibrado",
         bacia_id="TELES_PIRES_BACIA_FIXTURE")
    defaults.update(kwargs)
    return hidrograma_evento_cn(**defaults)

class TestHidrogramaBacia(unittest.TestCase):
    def test_evento_inteiro_usa_cn_acumulado_e_conserva_volume(self):
        r=basin()
        expected=escoamento_scs_cn(chuva_evento_mm=100,numero_curva=80,
            area_bacia_km2=120,fracao_abstracao_inicial=.2,
            fonte_cn="CN80 fixture solo e cobertura",
            fonte_chuva="CHIRPS 3 grade area hypotetica")
        self.assertAlmostEqual(r["escoamento_total_estimado_mm"],
                               expected["escoamento_direto_estimado_mm"],places=8)
        self.assertAlmostEqual(r["volume_previsto_m3"],r["volume_hidrograma_m3"],places=5)
        self.assertAlmostEqual(sum(q["vazao_direta_m3_s"]*3600 for q in r["hydrograma"]),
                               r["volume_previsto_m3"],places=5)
        self.assertEqual(len(r["hydrograma"]),7)
        self.assertAlmostEqual(sum(r["incrementos_excesso_mm"]),
                               r["escoamento_total_estimado_mm"],places=8)

    def test_cn_nao_aplicado_a_cada_pulso_isolado(self):
        r=basin(chuva_intervalos=rain([15,15,15,15]))
        total=escoamento_scs_cn(chuva_evento_mm=60,numero_curva=80,
              area_bacia_km2=120,fracao_abstracao_inicial=.2,
              fonte_cn="CN80 fixture solo e cobertura",
              fonte_chuva="CHIRPS 3 grade area hypotetica")["escoamento_direto_estimado_mm"]
        self.assertAlmostEqual(r["escoamento_total_estimado_mm"],total)
        isolated=4*escoamento_scs_cn(chuva_evento_mm=15,numero_curva=80,
              area_bacia_km2=120,fracao_abstracao_inicial=.2,
              fonte_cn="CN80 fixture solo e cobertura",
              fonte_chuva="CHIRPS 3 grade area hypotetica")["escoamento_direto_estimado_mm"]
        self.assertGreater(r["escoamento_total_estimado_mm"],isolated)

    def test_kernel_conserva_sem_desaparecer_cauda(self):
        r=basin(chuva_intervalos=rain([0.,100.]),
                resposta_unitaria_pesos=[.1,.2,.3,.2,.2])
        self.assertEqual(len(r["hydrograma"]),6)
        self.assertGreater(r["hydrograma"][-1]["vazao_direta_m3_s"],0)
        self.assertAlmostEqual(r["erro_conservacao_m3"],0,places=5)

    def test_sem_chuva_sem_vazao_direta(self):
        r=basin(chuva_intervalos=rain([0,0,0]))
        self.assertEqual(r["volume_previsto_m3"],0)
        self.assertEqual(r["vazao_pico_direta_m3_s"],0)

    def test_pesos_kernel_invalidos_bloqueados(self):
        for weights in ([.2,.2],[-1,2],[],[0,0],[".5",.5]):
            with self.subTest(weights=weights),self.assertRaises(ErroHidrograma):
                basin(resposta_unitaria_pesos=weights)

    def test_nunca_confundir_cotas_temperatura_ou_chuva_negativa(self):
        for series in (rain([5,-1,2]),rain([1,float("nan"),3])):
            with self.assertRaises(ErroHidrograma):
                basin(chuva_intervalos=series)

    def test_fuso_e_passos_regulares(self):
        bad=rain([0,30,50])
        bad[1]["data_hora"]="2025-02-01T01:00:00"
        with self.assertRaises(ErroHidrograma):basin(chuva_intervalos=bad)
        bad=rain([0,30,50]);bad[1]["data_hora"]=bad[0]["data_hora"]
        with self.assertRaises(ErroHidrograma):basin(chuva_intervalos=bad)
        bad=rain([0,30,50]);bad[2]["data_hora"]="2025-02-01T04:00:00Z"
        with self.assertRaises(ErroHidrograma):basin(chuva_intervalos=bad)

    def test_sem_area_bacia_nem_cadastro_nao_prediz(self):
        with self.assertRaises(ErroHidrograma):basin(area_bacia_km2=0)
        with self.assertRaises(ErroHidrograma):basin(bacia_id="")
        with self.assertRaises(ErroHidrograma):basin(numero_curva=110)

if __name__=="__main__":
    unittest.main()
