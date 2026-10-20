import unittest
from datetime import datetime,timedelta,timezone

from nivon.validacao_previsoes_ambientais import (
 ErroAvaliacaoAmbiental,validar_hindcast_ambiental,
 confrontar_grade_com_estacao,
)
UTC=timezone.utc

def regressao():
    start=datetime(2024,1,1,tzinfo=UTC)
    rows=[]
    for i in range(30):
        issued=start+timedelta(days=i)
        valid=issued+timedelta(hours=24)
        rows.append({"emitido_em":issued.isoformat(),"valido_em":valid.isoformat(),
            "feature_publicada_ate":(issued-timedelta(hours=1)).isoformat(),
            "observado_publicado_em":(valid+timedelta(hours=3)).isoformat(),
            "observado":10.0+i,"previsto":10.0+i,
            "baseline":9.0+i,"qualidade":"APROVADO"})
    return rows

def run(rows):return validar_hindcast_ambiental(
    registros=rows,fonte_modelo="modelo fixture versionado",
    variavel="VAZAO_M3_S",unidade="M3_S",
    estacao_id="15400000",horizonte_horas=24)

class TestForecastAsOf(unittest.TestCase):
    def test_perfeito_supera_baseline_sem_homologar(self):
        r=run(regressao())
        self.assertEqual(r["rmse"],0)
        self.assertEqual(r["baseline_rmse"],1)
        self.assertEqual(r["skill_mse_contra_baseline"],1)
        self.assertFalse(r["homologado"])

    def test_impede_feature_publicada_depois_da_previsao(self):
        rows=regressao()
        rows[0]["feature_publicada_ate"]=rows[0]["valido_em"]
        with self.assertRaises(ErroAvaliacaoAmbiental):run(rows)

    def test_impede_observacao_publicada_antes_do_evento(self):
        rows=regressao()
        rows[0]["observado_publicado_em"]=rows[0]["emitido_em"]
        with self.assertRaises(ErroAvaliacaoAmbiental):run(rows)

    def test_impede_horizonte_misto(self):
        rows=regressao()
        rows[0]["valido_em"]=(datetime(2024,1,1,tzinfo=UTC)+timedelta(hours=48)).isoformat()
        with self.assertRaises(ErroAvaliacaoAmbiental):run(rows)

    def test_duplica_ou_reprova_qc(self):
        rows=regressao()
        rows[-1]=dict(rows[0])
        with self.assertRaises(ErroAvaliacaoAmbiental):run(rows)
        rows=regressao();rows[0]["qualidade"]="SUSPEITO"
        with self.assertRaises(ErroAvaliacaoAmbiental):run(rows)

    def test_temperatura_negativa_e_permitida_se_nao_vazao(self):
        rows=regressao()
        for r in rows:r["observado"]=-5.;r["previsto"]=-6.;r["baseline"]=-5.
        with self.assertRaises(ErroAvaliacaoAmbiental):run(rows)
        x=validar_hindcast_ambiental(registros=rows,
                fonte_modelo="fixture",variavel="TMIN_C",unidade="CELSIUS",
                estacao_id="A801",horizonte_horas=24)
        self.assertEqual(x["mae"],1)

def grade():
    return [{"data":f"2026-09-{i:02d}","valor_estacao":10.,
            "valor_grade":12.,"qualidade_estacao":"APROVADO"} for i in range(1,31)]

def compare(rows):
    return confrontar_grade_com_estacao(pares_diarios=rows,
       estacao_id="A801",produto_grade="CHIRPS_V3",
       distancia_centro_grade_km=15,fonte_medida="INMET station",
       metrica="CHUVA_DIA_MM",unidade="MM")

class TestGradeEstacao(unittest.TestCase):
    def test_biais_grade_e_rmse(self):
        r=compare(grade())
        self.assertEqual(r["bias"],2)
        self.assertEqual(r["rmse"],2)
        self.assertEqual(r["n"],30)

    def test_sem_qc_ou_dia_faltando_bloqueia(self):
        rows=grade();rows[0]["qualidade_estacao"]="SUSPEITO"
        with self.assertRaises(ErroAvaliacaoAmbiental):compare(rows)
        with self.assertRaises(ErroAvaliacaoAmbiental):compare(grade()[:-1])

    def test_sem_duplicacao_de_dias(self):
        rows=grade();rows[-1]["data"]=rows[0]["data"]
        with self.assertRaises(ErroAvaliacaoAmbiental):compare(rows)

if __name__=="__main__":unittest.main()
