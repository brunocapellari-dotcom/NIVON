import unittest
from datetime import datetime,timedelta,timezone
from nivon.meteorologia_probabilistica import (
    ErroProbabilistico,crps_ensemble,avaliar_ensemble,
)

def sample(n=40):
    start=datetime(2023,1,1,tzinfo=timezone.utc)
    rows=[]
    for i in range(n):
        issue=start+timedelta(days=i)
        valid=issue+timedelta(hours=24)
        obs=10 if i%2 else 0
        members=[obs]*10
        rows.append({
            "emitido_em":issue.isoformat(),
            "valido_em":valid.isoformat(),
            "feature_publicada_ate":(issue-timedelta(hours=1)).isoformat(),
            "obs_publicado_em":(valid+timedelta(hours=2)).isoformat(),
            "observado":obs,"membros":members,
            "prob_climatologica":.5,"qc":"APROVADO",
            "modo_validacao":"FORA_AMOSTRA"
        })
    return rows

def verify(rows,**kwargs):
    opts=dict(registros=rows,variavel="CHUVA_ACUMULADA_MM",
              limiar_evento=5,horizonte_horas=24,
              modelo_id="ENS_2023_SIMULATED",local_id="MT_SORRISO_FIXTURE")
    opts.update(kwargs)
    return avaliar_ensemble(**opts)

class TestMeteorologiaProbabilistica(unittest.TestCase):
    def test_crps_referencia_ensemble(self):
        self.assertAlmostEqual(crps_ensemble(1,[0,2]),.5)
        self.assertAlmostEqual(crps_ensemble(2,[2,2,2]),0)
        self.assertAlmostEqual(crps_ensemble(0,[1,1]),1)

    def test_probabilidade_perfeita_sem_homologacao(self):
        r=verify(sample())
        self.assertEqual(r["brier_score"],0)
        self.assertEqual(r["crps_medio_na_unidade"],0)
        self.assertEqual(r["brier_climatologia"],.25)
        self.assertEqual(r["brier_skill_score"],1)
        self.assertEqual(r["n"],40)
        self.assertEqual(sum(x["n"] for x in r["calibracao_por_faixas"]),40)
        self.assertFalse(r["homologado"])

    def test_probabilidades_ruins_emite_skill_negativo(self):
        rows=sample()
        for r in rows:
            r["membros"]=[10 if r["observado"]==0 else 0]*10
        score=verify(rows)
        self.assertEqual(score["brier_score"],1)
        self.assertLess(score["brier_skill_score"],0)

    def test_horizonte_e_datas_futuras_bloqueados(self):
        rows=sample()
        rows[0]["feature_publicada_ate"]=rows[0]["valido_em"]
        with self.assertRaises(ErroProbabilistico):verify(rows)
        rows=sample();rows[0]["valido_em"]=(datetime(2023,1,3,tzinfo=timezone.utc)).isoformat()
        with self.assertRaises(ErroProbabilistico):verify(rows)
        rows=sample();rows[0]["obs_publicado_em"]=rows[0]["emitido_em"]
        with self.assertRaises(ErroProbabilistico):verify(rows)

    def test_sem_qualidade_ou_fora_amostra(self):
        rows=sample();rows[0]["qc"]="SUSPEITO"
        with self.assertRaises(ErroProbabilistico):verify(rows)
        rows=sample();rows[0]["modo_validacao"]="TREINO"
        with self.assertRaises(ErroProbabilistico):verify(rows)
        rows=sample();rows[0]["prob_climatologica"]=1.1
        with self.assertRaises(ErroProbabilistico):verify(rows)

    def test_sem_membros_numeros_invalidos_e_unidade(self):
        rows=sample();rows[0]["membros"]=[0]*9
        with self.assertRaises(ErroProbabilistico):verify(rows)
        rows=sample();rows[0]["membros"][1]=-999
        with self.assertRaises(ErroProbabilistico):verify(rows)
        rows=sample();rows[0]["observado"]=float("nan")
        with self.assertRaises(ErroProbabilistico):verify(rows)
        rows=sample();rows[0]["observado"]=-5
        r=verify(rows,variavel="TMIN_C",limiar_evento=0)
        self.assertEqual(r["n"],40)

    def test_nunca_usar_30_casos_insuficientes(self):
        with self.assertRaises(ErroProbabilistico):verify(sample(29))
        with self.assertRaises(ErroProbabilistico):crps_ensemble(0,[0])

    def test_duplicados_e_ausencia_de_fuso(self):
        rows=sample();rows[-1]=dict(rows[0])
        with self.assertRaises(ErroProbabilistico):verify(rows)
        rows=sample();rows[-1]["emitido_em"]="2023-02-09T00:00:00"
        with self.assertRaises(ErroProbabilistico):verify(rows)

if __name__=="__main__":
    unittest.main()
