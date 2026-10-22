"""Conab série histórica: limpeza dos tipos e preservação de nulidade."""
import unittest
from types import SimpleNamespace
from datetime import datetime, timezone
from nivon.conab_historico import normalizar_historico, SerieConabNaoHomologada

META=SimpleNamespace(source="conab_serie_historica",selected_source=None)
STAMP=datetime(2026,10,21,tzinfo=timezone.utc)
def r(**updates):
    row={"produto":"SOJA","safra":"2022/23","regiao":"CENTRO-OESTE",
         "uf":"MT","area_plantada_mil_ha":1200.5,
         "area_em_producao_mil_ha":None,"area_formacao_mil_ha":None,
         "area_colhida_mil_ha":1200.0,"producao_mil_ton":4000.3,
         "produtividade_kg_ha":3333.0}
    row.update(updates)
    return row
class TestHistoricoConab(unittest.TestCase):
    def test_preserva_area_colhida_que_levantamento_mensal_nao_tem(self):
        x=normalizar_historico([r()],META,"soja",coletado_em=STAMP)[0]
        self.assertEqual(x["metricas"]["area_colhida_mil_ha"],"1200.0")
        self.assertEqual(x["natureza"],"INFORMADO")
        self.assertIsNone(x["data_publicacao"])
        self.assertIsNone(x["data_referencia"])
    def test_ausencia_nao_e_zero(self):
        x=normalizar_historico([r(area_formacao_mil_ha=float("nan"),area_em_producao_mil_ha=0)],META,"soja",coletado_em=STAMP)[0]
        self.assertIsNone(x["metricas"]["area_formacao_mil_ha"])
        self.assertEqual(x["metricas"]["area_em_producao_mil_ha"],"0")
    def test_proveniencia_nao_pode_ser_fallback(self):
        with self.assertRaises(SerieConabNaoHomologada):
            normalizar_historico([r()],SimpleNamespace(source="conab"),"soja")
        with self.assertRaises(SerieConabNaoHomologada):
            normalizar_historico([r()],SimpleNamespace(source="conab_serie_historica",selected_source="ibge"),"soja")
    def test_nao_admite_safra_ou_uf_divergente(self):
        for bad in (r(uf="PR"),r(safra="2022/24"),r(safra="2027/28"),r(produto="MILHO")):
            with self.subTest(bad=bad),self.assertRaises(SerieConabNaoHomologada):
                normalizar_historico([bad],META,"soja")
    def test_sem_inferir_producao_e_nao_aceita_valores_anomalos(self):
        for bad in (r(producao_mil_ton="-1"),r(producao_mil_ton="inf"),r(producao_mil_ton=True)):
            with self.subTest(bad=bad),self.assertRaises(SerieConabNaoHomologada):
                normalizar_historico([bad],META,"soja")
    def test_duplicata_mesma_safra_bloqueada(self):
        with self.assertRaises(SerieConabNaoHomologada):
            normalizar_historico([r(),r(producao_mil_ton=4200)],META,"soja")
    def test_ordena_cronologicamente(self):
        x=normalizar_historico([r(safra="2023/24"),r()],META,"soja")
        self.assertEqual([v["safra"] for v in x],["2022/23","2023/24"])
if __name__=="__main__":
    unittest.main()
