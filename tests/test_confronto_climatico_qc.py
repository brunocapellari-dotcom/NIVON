import unittest
from datetime import date,timedelta
from hashlib import sha256
from nivon.confronto_climatico_qc import confronto_diario_inmet_power
from nivon.inmet_horario_qc import ErroINMETHorario


def inputs(days=30):
    rows=[];grid=[]
    for i in range(days):
        d=(date(2025,1,1)+timedelta(days=i)).isoformat()
        rows.append({"data_utc":d,"comparacao_grade_permitida":True,
                     "chuva_rotulo_utc_mm":10.0})
        grid.append({"data_utc":d,"valor":11.0,"unidade":"MM_DIA",
                     "latitude_grade":-12.4,"longitude_grade":-55.6,
                     "publicado_utc":"2025-02-05T12:00:00Z",
                     "primeira_coleta_utc":"2025-02-06T12:00:00Z",
                     "conteudo_sha256":sha256(b"power vintage").hexdigest()})
    raw=sha256(b"hourly CSV").hexdigest()
    diary={"status":"DIARIO_PRELIMINAR_NAO_HOMOLOGADO",
           "estacao":"A904","raw_sha256":raw,"dias":rows}
    qc={"aprovado":True,"estacao":"A904","raw_sha256":raw,
        "relatorio_sha256":sha256(b"external report").hexdigest()}
    return diary,grid,qc


class TestConfrontoEstacaoGrade(unittest.TestCase):
    def call(self,daycount=30,**updates):
        a,b,c=inputs(daycount)
        args=dict(diario_inmet=a,grade_nasa=b,coordenadas_estacao=(-12.4,-55.6),
                  qc_externo=c,fonte_coordenadas="INMET official station metadata",
                  corte_coleta="2026-01-01T12:00:00Z")
        args.update(updates)
        return confronto_diario_inmet_power(**args)

    def test_erro_grade_contra_estacao_nao_skill_preditivo(self):
        x=self.call()
        self.assertEqual(x["n"],30)
        self.assertAlmostEqual(x["mae"],1)
        self.assertAlmostEqual(x["bias"],1)
        self.assertFalse(x["homologado"])
        self.assertFalse(x["skill_preditiva_comprovada"])

    def test_sem_30_pares_nao_fabrica_rmse(self):
        x=self.call(29)
        self.assertEqual(x["status"],"COBERTURA_INSUFICIENTE_PARA_SCORE")
        self.assertNotIn("rmse",x)
        self.assertEqual(x["pares"],29)

    def test_sem_qc_independente_proibe_confronto(self):
        a,b,c=inputs()
        c["aprovado"]=False
        with self.assertRaises(ErroINMETHorario):
            self.call(diario_inmet=a,grade_nasa=b,qc_externo=c)

    def test_sem_intervalo_utc_comprovado_nao_pareia(self):
        a,b,c=inputs()
        a["dias"][0]["comparacao_grade_permitida"]=False
        x=self.call(diario_inmet=a,grade_nasa=b,qc_externo=c)
        self.assertEqual(x["pares"],29)

    def test_revisao_apos_corte_bloqueada(self):
        a,b,c=inputs()
        b[0]["publicado_utc"]="2028-01-01T12:00:00Z"
        with self.assertRaises(ErroINMETHorario):
            self.call(diario_inmet=a,grade_nasa=b,qc_externo=c)

    def test_distancia_muito_grande(self):
        with self.assertRaises(ErroINMETHorario):
            self.call(coordenadas_estacao=(0.0,-55.6))

    def test_duas_versoes_mesmo_dia_falha_fechada(self):
        a,b,c=inputs()
        b.append(dict(b[0]))
        with self.assertRaises(ErroINMETHorario):
            self.call(diario_inmet=a,grade_nasa=b,qc_externo=c)

    def test_nunca_converte_lacuna_em_zero(self):
        a,b,c=inputs()
        b[0]["valor"]=None
        x=self.call(diario_inmet=a,grade_nasa=b,qc_externo=c)
        self.assertEqual(x["pares"],29)

if __name__=="__main__":unittest.main()
