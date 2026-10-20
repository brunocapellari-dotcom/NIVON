import unittest
from nivon.tendencias_mdic import classificar_tendencia_mdic,ErroTendenciaMDIC
def serie(a=100.0,b=120.0):
    return {"serie":[(f"{ano}-{m:02d}",valor) for ano,valor in
           ((2024,a),(2025,b)) for m in range(1,13)],
           "classe":"SERIE_EXPLORATORIA_SEM_HOMOLOGACAO",
           "apta_publicacao_preditiva":False,"somente_dados_reais":False,
           "dataset_id":"MDIC_COMEX_NCM","codigo_produto":"12019000",
           "uf_fiscal_ou_ncm":"MT","variavel":"PESO_LIQUIDO_KG",
           "unidade":"kg","vintages":[{"ano":2024},{"ano":2025}]}
def ler(s,**kw):
    return classificar_tendencia_mdic(s,permitir_sinteticos_para_teste=True,**kw)
class TestTendenciaMDIC(unittest.TestCase):
    def test_alta_20pct(self):
        r=ler(serie())
        self.assertEqual(r["tendencia"],"ALTA")
        self.assertAlmostEqual(r["mediana_yoy_pct"],20)
        self.assertEqual(r["concordancia"],1)
        self.assertIsNone(r["probabilidade_de_movimento_futuro"])
        self.assertFalse(r["publicavel"])
    def test_baixa(self):
        self.assertEqual(ler(serie(100,80))["tendencia"],"BAIXA")
    def test_estabilidade(self):
        self.assertEqual(ler(serie(100,103))["tendencia"],"ESTABILIDADE")
    def test_misto_sem_consenso(self):
        s=serie()
        for i in range(12,18):s["serie"][i]=(s["serie"][i][0],80.0)
        self.assertEqual(ler(s)["tendencia"],"INDETERMINADA")
    def test_zeros_na_base_nao_criam_taxa(self):
        x=ler(serie(0,100))
        self.assertEqual(x["meses_validos"],0)
        self.assertEqual(x["tendencia"],"INDETERMINADA")
        self.assertEqual(len(x["sem_denominador"]),12)
    def test_meses_nao_consecutivos_rejeitados(self):
        s=serie();s["serie"][3]=("2024-05",100.0)
        with self.assertRaises(ErroTendenciaMDIC):ler(s)
    def test_sintetico_off_by_default(self):
        with self.assertRaises(PermissionError):
            classificar_tendencia_mdic(serie())
    def test_parametros_invalidos(self):
        for x in (0,100,float("nan"),True):
            with self.assertRaises(ErroTendenciaMDIC):ler(serie(),limiar_pct=x)
        for x in (0.5,0,1.1):
            with self.assertRaises(ErroTendenciaMDIC):ler(serie(),consenso_minimo=x)
    def test_valor_nao_finito(self):
        for v in (-1,float("inf"),float("nan")):
            s=serie();s["serie"][-1]=(s["serie"][-1][0],v)
            with self.assertRaises(ErroTendenciaMDIC):ler(s)
    def test_falsa_permissao_nao_libera(self):
        s=serie();s["apta_publicacao_preditiva"]=True
        with self.assertRaises(ErroTendenciaMDIC):ler(s)
    def test_yoy_nao_e_frete(self):
        r=ler(serie())
        self.assertFalse(r["fluxo_fisico_ou_frete_inferido"])
        self.assertEqual(r["metodo"],"COMPARACAO_MENSAL_MESMO_MES_ANO_ANTERIOR")
