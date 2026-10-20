import unittest
from datetime import datetime,timezone,timedelta
from nivon.hidrologia_chuva_vazao import (
    ErroChuvaVazao,escoamento_scs_cn,propagar_muskingum,
)

def scs(**kw):
    d=dict(chuva_evento_mm=100,numero_curva=80,area_bacia_km2=100,
           fracao_abstracao_inicial=.2,fonte_cn="Solo e cobertura fixture",
           fonte_chuva="Evento fixture hidrologico")
    d.update(kw)
    return escoamento_scs_cn(**d)

def dados(entrada=(10,20,40,20,10),step=1):
    start=datetime(2025,1,1,tzinfo=timezone.utc)
    return [{"data_hora":(start+timedelta(hours=i*step)).isoformat(),
             "vazao_entrada_m3_s":val}
            for i,val in enumerate(entrada)]

def rota(**kw):
    d=dict(serie_entrada=dados(),passo_horas=1,tempo_viagem_k_h=2,
           peso_x=.25,vazao_saida_inicial_m3_s=10,
           fonte_calibracao="Parâmetros hipotéticos HEC HMS")
    d.update(kw)
    return propagar_muskingum(**d)

class TestSCSCN(unittest.TestCase):
    def test_formula_nrsc(self):
        x=scs()
        self.assertAlmostEqual(x["retencao_potencial_mm"],63.5)
        self.assertAlmostEqual(x["abstracao_inicial_mm"],12.7)
        q=(100-12.7)**2/(100+.8*63.5)
        self.assertAlmostEqual(x["escoamento_direto_estimado_mm"],q)
        self.assertAlmostEqual(x["escoamento_evento_m3"],q*100_000)
        self.assertAlmostEqual(x["demais_perdas_estimadas_mm"]+q,100)

    def test_chuva_insuficiente_nao_gera_runoff(self):
        self.assertEqual(scs(chuva_evento_mm=10)["escoamento_direto_estimado_mm"],0)
        self.assertEqual(scs(chuva_evento_mm=0)["fracao_escoamento"],0)

    def test_cn_cem_gera_runoff_toda_chuva(self):
        self.assertAlmostEqual(scs(numero_curva=100)["escoamento_direto_estimado_mm"],100)

    def test_fisica_bad_inputs(self):
        for params in ({"numero_curva":0},{"numero_curva":101},
                       {"fracao_abstracao_inicial":2},{"area_bacia_km2":0},
                       {"chuva_evento_mm":-1},{"chuva_evento_mm":float("nan")},
                       {"numero_curva":True},{"fonte_chuva":""}):
            with self.subTest(params=params),self.assertRaises(ErroChuvaVazao):
                scs(**params)

class TestMuskingum(unittest.TestCase):
    def test_coeficientes_e_hidrograma(self):
        r=rota()
        self.assertAlmostEqual(sum(r["coeficientes"].values()),1)
        self.assertAlmostEqual(r["coeficientes"]["C0"],0)
        self.assertAlmostEqual(r["coeficientes"]["C1"],.5)
        self.assertAlmostEqual(r["coeficientes"]["C2"],.5)
        self.assertEqual(r["pontos"][0]["saida_modelada_m3_s"],10)
        self.assertEqual(r["pontos"][1]["saida_modelada_m3_s"],10)
        self.assertEqual(r["pontos"][2]["saida_modelada_m3_s"],15)
        self.assertLess(r["max_erro_balanco_m3"],1e-6)

    def test_q_constante_preserva_q(self):
        r=rota(serie_entrada=dados([50]*12),
               vazao_saida_inicial_m3_s=50)
        self.assertTrue(all(abs(p["saida_modelada_m3_s"]-50)<1e-9 for p in r["pontos"]))

    def test_instabilidade_de_dt_bloqueada(self):
        with self.assertRaises(ErroChuvaVazao):rota(passo_horas=.2)
        with self.assertRaises(ErroChuvaVazao):rota(passo_horas=4)
        with self.assertRaises(ErroChuvaVazao):rota(peso_x=.6)

    def test_lacuna_temporal_rejeitada(self):
        r=dados()
        r[2]["data_hora"]=(datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(hours=4)).isoformat()
        with self.assertRaises(ErroChuvaVazao):rota(serie_entrada=r)

    def test_vazao_negativa_e_fuso_invalido(self):
        x=dados();x[2]["vazao_entrada_m3_s"]=-1
        with self.assertRaises(ErroChuvaVazao):rota(serie_entrada=x)
        y=dados();y[1]["data_hora"]="2025-01-01T01:00:00"
        with self.assertRaises(ErroChuvaVazao):rota(serie_entrada=y)

if __name__=="__main__":unittest.main()
