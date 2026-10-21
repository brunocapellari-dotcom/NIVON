import unittest
from datetime import datetime,timedelta,timezone
from copy import deepcopy
from nivon.ensemble_hidrologico_bacia import cenario_ensemble_bacia,ErroEnsembleBacia

ISSUE="2026-10-15T00:00:00Z"
START=datetime(2026,10,15,1,tzinfo=timezone.utc)

def rainfall(pulses):
    return [{"data_hora":(START+timedelta(hours=i)).isoformat(),
             "chuva_area_mm":float(mm)} for i,mm in enumerate(pulses)]

def example():
    return [
        {"membro_id":"gefs01","chuva_intervalos":rainfall([0,10,15,5,0])},
        {"membro_id":"gefs02","chuva_intervalos":rainfall([0,20,20,15,0])},
        {"membro_id":"gefs03","chuva_intervalos":rainfall([0,40,60,40,0])},
    ]

def evaluate(members=None,**changes):
    args=dict(
        membros_chuva=example() if members is None else members,
        emitido_em=ISSUE,dados_publicados_ate="2026-10-14T22:00:00Z",
        passo_horas=1,area_bacia_km2=100,numero_curva=80,
        fracao_abstracao_inicial=.2,resposta_unitaria_pesos=[.2,.5,.3],
        limiar_pico_direto_m3_s=300,bacia_id="TELES_PIRES_TESTE_SUBBACIA",
        fonte_modelo_chuva="GEFS 20261015 UTC fixture",
        fonte_cn="CN80 solo hipotetico de sub-bacia",
        fonte_resposta_unitaria="Kernel UH fixture nao calibrado",
        fonte_limiar="Cenario 300 m3s de escoamento direto, nao alerta",
    )
    args.update(changes)
    return cenario_ensemble_bacia(**args)

class TestEnsembleHidrologicoBacia(unittest.TestCase):
    def test_cenarios_diferentes_geram_quantis_ordenados(self):
        r=evaluate()
        self.assertEqual(r["membros"],3)
        q=r["pico_direto_quantiles_m3_s"]
        self.assertLessEqual(q["p10"],q["p50"])
        self.assertLessEqual(q["p50"],q["p90"])
        self.assertEqual(r["estado_ensemble"],"DISPERSAO_CENARIOS_NAO_CALIBRADA")
        self.assertFalse(r["probabilidade_calibrada"])
        self.assertFalse(r["alerta_hidrologico_oficial"])
        self.assertFalse(r["previsao_operacional_homologada"])
        self.assertEqual(len(r["resultados_membros"][0]["hidrograma"]),7)

    def test_eventos_modelados_e_probabilidades_limites(self):
        r=evaluate(limiar_pico_direto_m3_s=0)
        self.assertEqual(r["fracao_membros_pico_direto_acima_ou_igual_limiar"],1)
        r=evaluate(limiar_pico_direto_m3_s=1_000_000)
        self.assertEqual(r["fracao_membros_pico_direto_acima_ou_igual_limiar"],0)

    def test_mesmos_membros_sem_dispersao_nao_e_probabilidade_confiavel(self):
        m=example()
        for item in m[1:]:
            item["chuva_intervalos"]=deepcopy(m[0]["chuva_intervalos"])
        r=evaluate(members=m)
        self.assertEqual(r["estado_ensemble"],"SEM_DISPERSAO_IDENTIFICADA")
        self.assertFalse(r["probabilidade_calibrada"])

    def test_conservacao_volume_cada_membro(self):
        r=evaluate()
        for item in r["resultados_membros"]:
            volume=sum(x["vazao_direta_m3_s"]*3600 for x in item["hidrograma"])
            self.assertAlmostEqual(volume,item["volume_direto_m3"],places=5)

    def test_erro_membros_desalinhados_temporalmente(self):
        m=example()
        m[1]["chuva_intervalos"][2]["data_hora"]="2026-10-15T04:00:00Z"
        with self.assertRaises(ErroEnsembleBacia):evaluate(members=m)

    def test_limiar_invalido_ou_se_fonte_ausente(self):
        with self.assertRaises(ErroEnsembleBacia):
            evaluate(limiar_pico_direto_m3_s=-1)
        with self.assertRaises(ErroEnsembleBacia):
            evaluate(fonte_limiar="")

    def test_sem_vintage_ou_emissao_valida(self):
        with self.assertRaises(ErroEnsembleBacia):
            evaluate(dados_publicados_ate="2026-10-15T10:00:00Z")
        with self.assertRaises(ErroEnsembleBacia):
            evaluate(emitido_em="2026-10-15T01:00:00Z")
        with self.assertRaises(ErroEnsembleBacia):
            evaluate(emitido_em="2026-10-15T00:00:00")

    def test_sem_chuva_areal_ou_com_nan(self):
        m=example();m[0]["chuva_intervalos"][0]["chuva_area_mm"]=-1
        with self.assertRaises(ErroEnsembleBacia):evaluate(members=m)
        m=example();m[0]["chuva_intervalos"][0]["chuva_area_mm"]=float("nan")
        with self.assertRaises(ErroEnsembleBacia):evaluate(members=m)

    def test_identificadores_e_numero_membros(self):
        m=example();m[1]["membro_id"]=m[0]["membro_id"]
        with self.assertRaises(ErroEnsembleBacia):evaluate(members=m)
        with self.assertRaises(ErroEnsembleBacia):evaluate(members=example()[:2])

    def test_ausencia_de_parametros_de_bacia(self):
        with self.assertRaises(ErroEnsembleBacia):
            evaluate(area_bacia_km2=0)
        with self.assertRaises(ErroEnsembleBacia):
            evaluate(resposta_unitaria_pesos=[.2,.2])
        with self.assertRaises(ErroEnsembleBacia):
            evaluate(numero_curva=120)

if __name__=="__main__":unittest.main()
