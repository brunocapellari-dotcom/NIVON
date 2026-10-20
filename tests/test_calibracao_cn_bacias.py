import unittest
from datetime import datetime,timedelta,timezone
from nivon.calibracao_cn_bacias import calibrar_cn_historico,ErroCalibracaoBacia
from nivon.hidrologia_chuva_vazao import escoamento_scs_cn

def fixture():
    start=datetime(2022,1,1,tzinfo=timezone.utc)
    rows=[]
    for i in range(42):
        event=start+timedelta(days=i)
        rain=25+(i%10)*10
        q=escoamento_scs_cn(chuva_evento_mm=rain,numero_curva=75,
            area_bacia_km2=1,fracao_abstracao_inicial=.2,
            fonte_chuva="CHIRPS Test Historic Rain",fonte_cn="Fixture Soil CN75")["escoamento_direto_estimado_mm"]
        rows.append({"evento_em":event.isoformat(),
          "publicado_em":(event+timedelta(hours=2)).isoformat(),
          "chuva_publicada_em":(event+timedelta(hours=2)).isoformat(),
          "chuva_areal_mm":rain,"escoamento_observado_mm":q,
          "qualidade":"APROVADO"})
    return rows

def run(rows,**extra):
    opts=dict(eventos=rows,treino_ate="2022-01-31T00:00:00Z",
              cn_candidatos=[65,70,75,80,85],
              fracao_abstracao_inicial=.2,bacia_id="BACIA_TESTE_TELES_PIRES",
              fonte_solo="CN 75 hypothetical soil",
              fonte_chuva="CHIRPS historical synthetic")
    opts.update(extra)
    return calibrar_cn_historico(**opts)

class TestCalibracaoCNSemVazamento(unittest.TestCase):
    def test_recupera_cn_no_treino_e_nunca_promove(self):
        r=run(fixture())
        self.assertEqual(r["cn_selecionado"],75)
        self.assertEqual(r["eventos_treino"],30)
        self.assertEqual(r["eventos_holdout"],12)
        self.assertAlmostEqual(r["rmse_holdout_mm"],0,places=10)
        self.assertAlmostEqual(r["skill_mse_baseline"],1,places=10)
        self.assertFalse(r["promocao_automatica"])

    def test_holdout_alterado_nao_muda_cn_do_treino(self):
        a=fixture();ref=run(a)["cn_selecionado"]
        for r in a[30:]:r["escoamento_observado_mm"]=0
        b=run(a)
        self.assertEqual(b["cn_selecionado"],ref)
        self.assertGreater(b["rmse_holdout_mm"],0)

    def test_publicado_depois_do_corte_nao_treina(self):
        rows=fixture()
        for r in rows[:16]:
            r["publicado_em"]="2022-03-01T00:00:00Z"
        with self.assertRaises(ErroCalibracaoBacia):run(rows)

    def test_eventos_duplicados_e_desordenados(self):
        rows=fixture();rows[1]=dict(rows[0])
        with self.assertRaises(ErroCalibracaoBacia):run(rows)
        rows=fixture();rows[10],rows[11]=rows[11],rows[10]
        with self.assertRaises(ErroCalibracaoBacia):run(rows)

    def test_treino_e_teste_obrigatorios(self):
        with self.assertRaises(ErroCalibracaoBacia):run(fixture()[:25])
        with self.assertRaises(ErroCalibracaoBacia):
            run(fixture(),treino_ate="2022-02-15T00:00:00Z")

    def test_qualidade_cnp_estourado_e_divisao_fisica(self):
        rows=fixture();rows[0]["qualidade"]="RUIM"
        with self.assertRaises(ErroCalibracaoBacia):run(rows)
        with self.assertRaises(ErroCalibracaoBacia):
            run(fixture(),cn_candidatos=[200,75])
        rows=fixture();rows[0]["escoamento_observado_mm"]=9999
        with self.assertRaises(ErroCalibracaoBacia):run(rows)

if __name__=="__main__":
    unittest.main()
