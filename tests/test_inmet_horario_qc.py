import unittest
from nivon.inmet_horario_qc import ErroINMETHorario,extrair_horarios_inmet,agregar_dias_inmet


def fixture(*,hours=24,rain_missing=(),temp_missing=(),dup=False,station="A904",
            date="2025-01-02",unit="HORÁRIO",sep=","):
    head="CODIGO (WMO):;"+station+"\nESTAÇÃO:;SORRISO\n"
    head+="Data;Hora UTC;PRECIPITAÇÃO TOTAL, HORÁRIO (mm);TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)\n"
    records=[]
    for hour in range(hours):
        rain="" if hour in rain_missing else ("1,5" if sep=="," else "1.5")
        temp="" if hour in temp_missing else ("25,0" if sep=="," else "25.0")
        records.append(f"{date};{hour:02d}00 UTC;{rain};{temp}")
    if dup:records.append(records[0])
    return (head+"\n".join(records)+"\n").encode("utf-8")


class TestCSVHorariaINMET(unittest.TestCase):
    def extract(self,**kw):
        return extrair_horarios_inmet(csv_bytes=fixture(**kw),estacao_esperada="A904",ano_esperado=2025)

    def test_24_horas_completas_nao_sao_qc_final(self):
        p=self.extract()
        self.assertEqual(p["linhas"],24)
        d=agregar_dias_inmet(pacote=p)
        self.assertEqual(d["dias"][0]["chuva_rotulo_utc_mm"],36)
        self.assertFalse(d["dias"][0]["comparacao_grade_permitida"])
        self.assertEqual(d["dias"][0]["qc_sensor"],"NAO_HOMOLOGADO")
        self.assertFalse(d["liberacao_preditiva"])

    def test_faltantes_nunca_viram_chuva_zero(self):
        d=agregar_dias_inmet(pacote=self.extract(rain_missing=(4,)))
        row=d["dias"][0]
        self.assertIsNone(row["chuva_rotulo_utc_mm"])
        self.assertEqual(row["horas_chuva_validas"],23)
        self.assertFalse(row["comparacao_grade_permitida"])

    def test_dia_com_23_horas_nao_tem_agregado(self):
        d=agregar_dias_inmet(pacote=self.extract(hours=23))
        self.assertIsNone(d["dias"][0]["chuva_rotulo_utc_mm"])

    def test_utc_semantica_precisa_evidencia(self):
        p=self.extract()
        with self.assertRaises(ErroINMETHorario):
            agregar_dias_inmet(pacote=p,convencao_intervalo_chuva_confirmada=True)
        result=agregar_dias_inmet(pacote=p,convencao_intervalo_chuva_confirmada=True,
            referencia_convencao="METADADO_OFICIAL_INTERVALO_UTC_VERIFICADO")
        self.assertTrue(result["dias"][0]["comparacao_grade_permitida"])
        self.assertEqual(result["dias"][0]["qc_sensor"],"NAO_HOMOLOGADO")

    def test_sem_inventar_extremo_diario_de_sensor(self):
        d=agregar_dias_inmet(pacote=self.extract(temp_missing=(7,)))
        self.assertIsNone(d["dias"][0]["tmax_bulbo_amostrada_c"])
        self.assertIsNone(d["dias"][0]["tmin_bulbo_amostrada_c"])

    def test_deduplicacao_e_estacao(self):
        with self.assertRaises(ErroINMETHorario):self.extract(dup=True)
        with self.assertRaises(ErroINMETHorario):self.extract(station="A905")
        with self.assertRaises(ErroINMETHorario):self.extract(date="2024-12-31")

    def test_rejeita_valores_fisicamente_invalidos(self):
        original=fixture()
        with self.assertRaises(ErroINMETHorario):
            extrair_horarios_inmet(csv_bytes=original.replace(b"1,5",b"-1,5",1),
                estacao_esperada="A904",ano_esperado=2025)

    def test_sem_hora_incomum(self):
        data=fixture().replace(b"0100 UTC",b"2460 UTC",1)
        with self.assertRaises(ErroINMETHorario):
            extrair_horarios_inmet(csv_bytes=data,estacao_esperada="A904",ano_esperado=2025)

    def test_null_em_vez_de_zero(self):
        data=fixture().replace(b";1,5;",b";9999;",1)
        x=extrair_horarios_inmet(csv_bytes=data,estacao_esperada="A904",ano_esperado=2025)
        self.assertIsNone(x["observacoes"][0]["chuva_hora_mm"])

if __name__=="__main__":unittest.main()
