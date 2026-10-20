import unittest
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from nivon.auditoria_safra_preditiva import avaliar_backtest_safra,ErroBacktestSafra


def records(*,skill=True,years=10,cities=4):
    cases=[]
    hashed=sha256(b"synthetic fixtures no claim of live").hexdigest()
    for ano in range(2010,2010+years):
        for city in range(cities):
            base_yield=3500+10*(ano-2010)+12*city
            observed=base_yield+(-50 if city%2 else 50)
            cases.append({
                "municipio_ibge":f"510{1000+city:04d}", "ano_colheita":ano,
                "origem":f"{ano}-02-01T12:00:00-04:00",
                "feature_disponivel_em":f"{ano}-01-31T12:00:00-04:00",
                "baseline_disponivel_em":f"{ano}-01-01T12:00:00-04:00",
                "modelo_gerado_em":f"{ano}-02-01T10:00:00-04:00",
                "colheita_encerrada_em":f"{ano}-06-01T12:00:00-04:00",
                "observado_publicado_em":f"{ano}-07-01T12:00:00-04:00",
                "observado_coletado_em":f"{ano}-07-02T12:00:00-04:00",
                "ultima_safra_treinada":ano-1,
                "observado_kg_ha":observed,
                "previsto_kg_ha":observed+(10 if skill else 200),
                "baseline_kg_ha":observed+100,
                "observado_raw_sha256":hashed,
                "previsao_sha256":hashed,
                "estado_teste":"FORA_AMOSTRA_DECLARADO",
            })
    return cases


class TestAuditoriaSafra(unittest.TestCase):
    def run_eval(self,data=None,**kwargs):
        params=dict(registros=records() if data is None else data,
            cultura="SOJA",modelo_id="NIVON_TEST_V1",horizonte_min_dias=110,
            horizonte_max_dias=130,repeticoes_bootstrap=300,semente=33)
        params.update(kwargs)
        return avaliar_backtest_safra(**params)

    def test_ganho_deterministico_com_bloco_anos(self):
        r=self.run_eval()
        self.assertEqual(r["n"],40)
        self.assertEqual(r["municipios"],4)
        self.assertAlmostEqual(r["global"]["mae"],10)
        self.assertAlmostEqual(r["global"]["mae_baseline"],100)
        self.assertAlmostEqual(r["ganho_mae_anos_iguais"],.9)
        self.assertEqual(r["intervalo_bootstrap_ganho_mae_anos_iguais"],[.9,.9])
        self.assertEqual(r["intervalo_bootstrap_ganho_mae_anos_iguais"],self.run_eval()["intervalo_bootstrap_ganho_mae_anos_iguais"])
        self.assertFalse(r["habilita_previsao"])

    def test_nao_vence_baseline_nao_inventa_skill(self):
        r=self.run_eval(records(skill=False))
        self.assertFalse(r["superou_baseline_global_mae_rmse"])
        self.assertLess(r["ganho_mae_anos_iguais"],0)
        self.assertFalse(r["limite_inferior_ganho_positivo"])

    def test_detecta_data_vazando(self):
        rows=records()
        rows[0]["feature_disponivel_em"]="2020-01-01T12:00:00Z"
        with self.assertRaises(ErroBacktestSafra):self.run_eval(rows)

    def test_treino_futuro_e_observacao_publicada_antes_colheita(self):
        rows=records();rows[0]["ultima_safra_treinada"]=2010
        with self.assertRaises(ErroBacktestSafra):self.run_eval(rows)
        rows=records();rows[0]["observado_publicado_em"]="2010-03-01T12:00:00Z"
        with self.assertRaises(ErroBacktestSafra):self.run_eval(rows)

    def test_nao_duplica_municipio_ano(self):
        rows=records();rows.append(dict(rows[0]))
        with self.assertRaises(ErroBacktestSafra):self.run_eval(rows)

    def test_ano_ou_municipio_insuficientes_reprovados(self):
        r=self.run_eval(records(years=7,cities=4))
        self.assertEqual(r["status"],"REPROVADO_COBERTURA_HISTORICA")
        r=self.run_eval(records(years=10,cities=2))
        self.assertEqual(r["status"],"REPROVADO_COBERTURA_HISTORICA")

    def test_numero_infinito_bool_negativo_e_unidade_implicita(self):
        for bad in (float("nan"),float("inf"),True,-4,"3900"):
            rows=records();rows[0]["observado_kg_ha"]=bad
            with self.assertRaises(ErroBacktestSafra):self.run_eval(rows)

    def test_distancia_horizonte_nao_mistura_previsoes(self):
        rows=records()
        rows[0]["origem"]="2010-05-29T12:00:00Z"
        with self.assertRaises(ErroBacktestSafra):self.run_eval(rows)

    def test_baseline_zero_retorna_null_ao_inves_de_div_zero(self):
        rows=records()
        for r in rows:r["baseline_kg_ha"]=r["observado_kg_ha"]
        x=self.run_eval(rows)
        self.assertIsNone(x["global"]["ganho_mae"])
        self.assertIsNone(x["ganho_mae_anos_iguais"])
        self.assertIsNone(x["intervalo_bootstrap_ganho_mae_anos_iguais"])

if __name__=="__main__":unittest.main()
