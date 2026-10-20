import unittest
from datetime import datetime,timedelta,timezone
from copy import deepcopy
from nivon.chuva_areal_ensemble import agregar_ensemble_chuva_areal,ErroChuvaAreal
from nivon.ensemble_hidrologico_bacia import cenario_ensemble_bacia

START=datetime(2026,10,16,1,tzinfo=timezone.utc)

def rain(values):
    return [{"data_hora":(START+timedelta(hours=i)).isoformat(),
             "chuva_mm":float(v)} for i,v in enumerate(values)]

def members():
    return [
        {"membro_id":"GEFS_01","celulas":[
          {"celula_id":"cell_A","serie":rain([0,4,10,0])},
          {"celula_id":"cell_B","serie":rain([0,8,6,0])}]},
        {"membro_id":"GEFS_02","celulas":[
          {"celula_id":"cell_A","serie":rain([0,8,20,0])},
          {"celula_id":"cell_B","serie":rain([0,16,12,0])}]},
        {"membro_id":"GEFS_03","celulas":[
          {"celula_id":"cell_A","serie":rain([0,16,40,0])},
          {"celula_id":"cell_B","serie":rain([0,32,24,0])}]}
    ]

def run(**changes):
    args=dict(bacia_id="TELES_PIRES_GIS_FIXTURE",
              area_bacia_km2=100,pesos_celulas=[
                  {"celula_id":"cell_A","peso_area":.25},
                  {"celula_id":"cell_B","peso_area":.75}
              ],pesos_sha256="a"*64,
              metodo_geoespacial="interseccao GeoTIFF shapefile fixture WGS84",
              produto_previsao="NOAA_GEFS_ENSEMBLE",
              versao_previsao="2026-10-16T00Z GEFS scenario",
              emitido_em="2026-10-16T00:00:00Z",
              dados_publicados_ate="2026-10-15T23:00:00Z",
              passo_horas=1,membros_grade=members())
    args.update(changes)
    return agregar_ensemble_chuva_areal(**args)

class TestAgregacaoChuvaAreal(unittest.TestCase):
    def test_media_ponderada_fechamento_e_sem_dados_inventados(self):
        v=run()
        self.assertEqual(v["membros"],3)
        self.assertEqual(v["celulas_por_membro"],2)
        self.assertEqual(v["membros_chuva"][0]["chuva_intervalos"][1]["chuva_area_mm"],7.)
        self.assertEqual(v["membros_chuva"][0]["chuva_intervalos"][2]["chuva_area_mm"],7.)
        self.assertFalse(v["intersecao_gis_auditada_externamente"])
        self.assertFalse(v["calibracao_validada"])

    def test_conexao_ponderacao_para_hidrograma_ensemble(self):
        v=run()
        out=cenario_ensemble_bacia(
            membros_chuva=v["membros_chuva"],
            emitido_em=v["emitido_em_utc"],
            dados_publicados_ate=v["dados_publicados_ate_utc"],
            passo_horas=v["passo_horas"],
            area_bacia_km2=v["area_bacia_km2"],
            numero_curva=82,fracao_abstracao_inicial=.2,
            resposta_unitaria_pesos=[.2,.5,.3],
            limiar_pico_direto_m3_s=200,
            bacia_id=v["bacia_id"],fonte_modelo_chuva="GEFS scenario with GIS area weights",
            fonte_cn="CN 82 fixture soil catchment",
            fonte_resposta_unitaria="Unit hydrograph non-calibrated fixture",
            fonte_limiar="Conditional direct runoff scenario threshold"
        )
        self.assertEqual(out["membros"],3)
        self.assertFalse(out["probabilidade_calibrada"])
        self.assertGreater(out["pico_direto_quantiles_m3_s"]["p90"],out["pico_direto_quantiles_m3_s"]["p10"])

    def test_pesos_que_nao_somam_um_bloqueados(self):
        w=[{"celula_id":"cell_A","peso_area":.2},
           {"celula_id":"cell_B","peso_area":.7}]
        with self.assertRaises(ErroChuvaAreal):run(pesos_celulas=w)

    def test_peso_nulo_duplicado_ou_sha_sem_origem(self):
        for w in ([
              {"celula_id":"cell_A","peso_area":0},
              {"celula_id":"cell_B","peso_area":1}
            ],[
              {"celula_id":"cell_A","peso_area":.5},
              {"celula_id":"cell_A","peso_area":.5}
            ]):
            with self.assertRaises(ErroChuvaAreal):run(pesos_celulas=w)
        with self.assertRaises(ErroChuvaAreal):run(pesos_sha256="sem_hash")

    def test_celula_faltando_ou_desconhecida(self):
        m=members();m[1]["celulas"].pop()
        with self.assertRaises(ErroChuvaAreal):run(membros_grade=m)
        m=members();m[1]["celulas"][0]["celula_id"]="cell_FAKE"
        with self.assertRaises(ErroChuvaAreal):run(membros_grade=m)

    def test_nao_preencher_faltantes_ou_sentinela(self):
        m=members();m[0]["celulas"][0]["serie"][2]["chuva_mm"]=None
        with self.assertRaises(ErroChuvaAreal):run(membros_grade=m)
        m=members();m[0]["celulas"][0]["serie"][2]["chuva_mm"]=-999.
        with self.assertRaises(ErroChuvaAreal):run(membros_grade=m)

    def test_janelas_todas_iguais_e_utc(self):
        m=members();m[1]["celulas"][1]["serie"][2]["data_hora"]="2026-10-16T04:00:00Z"
        with self.assertRaises(ErroChuvaAreal):run(membros_grade=m)
        m=members();m[1]["celulas"][1]["serie"][2]["data_hora"]="2026-10-16T03:00:00"
        with self.assertRaises(ErroChuvaAreal):run(membros_grade=m)

    def test_vintage_da_emissao_nao_pode_ser_futura(self):
        with self.assertRaises(ErroChuvaAreal):
            run(dados_publicados_ate="2026-10-16T05:00:00Z")
        with self.assertRaises(ErroChuvaAreal):
            run(emitido_em="2026-10-16T01:00:00Z")

    def test_membros_repetidos_bloqueados(self):
        m=members();m[1]["membro_id"]="GEFS_01"
        with self.assertRaises(ErroChuvaAreal):run(membros_grade=m)
        with self.assertRaises(ErroChuvaAreal):run(membros_grade=members()[:2])

if __name__=="__main__":
    unittest.main()
