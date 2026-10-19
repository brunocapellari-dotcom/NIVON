import tempfile
import unittest
from pathlib import Path
from nivon.mdic_importacao import COLUNAS, ErroImportacao, resumir_importacao_csv

class TestImportacaoNCM(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.arq=Path(t.name)/"IMP_2026.csv"
    def linha(self,**p):
        d=dict(CO_ANO="2026",CO_MES="09",CO_NCM="31021010",CO_UNID="10",
               CO_PAIS="160",SG_UF_NCM="MT",CO_VIA="01",CO_URF="081",
               QT_ESTAT="1",KG_LIQUIDO="2000",VL_FOB="800",
               VL_FRETE="150",VL_SEGURO="20")
        d.update(p)
        return ";".join(d[x] for x in COLUNAS)
    def gravar(self,linhas):
        self.arq.write_text(";".join(COLUNAS)+"\n"+"\n".join(linhas)+"\n",encoding="utf-8")
    def processar(self,**kw):
        return resumir_importacao_csv(self.arq,ncms=frozenset({"31021010"}),**kw)
    def test_fob_frete_seguro_cif(self):
        self.gravar([self.linha()])
        r=self.processar()
        x=r["recortes"][0]
        self.assertEqual((x["toneladas"],x["valor_fob_usd"],x["frete_internacional_usd"]), (2,800,150))
        self.assertEqual(x["valor_cif_calculado_usd"],970)
        self.assertEqual(x["cif_usd_t"],485)
        self.assertTrue(x["nao_municipio"])
        self.assertIsNone(r["publicacao"])
    def test_agregacao_chave(self):
        self.gravar([self.linha(),self.linha(KG_LIQUIDO="3000",VL_FOB="1200")])
        x=self.processar()["recortes"][0]
        self.assertEqual(x["peso_liquido_kg"],5000)
        self.assertEqual(x["valor_cif_calculado_usd"],2340)
    def test_paises_vias_urf_distintos(self):
        self.gravar([self.linha(),self.linha(CO_PAIS="249"),self.linha(CO_URF="082")])
        self.assertEqual(len(self.processar()["recortes"]),3)
    def test_uf_nao_identificada(self):
        self.gravar([self.linha(SG_UF_NCM="ND")])
        self.assertFalse(self.processar()["recortes"][0]["uf_brasileira"])
    def test_ncm_fora_filtro_nao_vira_zero(self):
        self.gravar([self.linha(CO_NCM="12019000")])
        with self.assertRaises(ErroImportacao):self.processar()
    def test_ncm_invalido(self):
        self.gravar([self.linha(CO_NCM="12")])
        with self.assertRaises(ErroImportacao):self.processar()
    def test_ano_mes(self):
        for k,v in (("CO_ANO","1899"),("CO_MES","13")):
            self.gravar([self.linha(**{k:v})])
            with self.assertRaises(ErroImportacao):self.processar()
    def test_numeros_negativos(self):
        for k in ("VL_FOB","VL_FRETE","VL_SEGURO","KG_LIQUIDO"):
            self.gravar([self.linha(**{k:"-1"})])
            with self.assertRaises(ErroImportacao):self.processar()
    def test_sem_divisao_por_zero(self):
        self.gravar([self.linha(KG_LIQUIDO="0")])
        self.assertIsNone(self.processar()["recortes"][0]["cif_usd_t"])
    def test_layout_exportacao_nao_aceito(self):
        self.arq.write_text("CO_ANO;CO_NCM\n2026;31021010\n")
        with self.assertRaises(ErroImportacao):self.processar()
    def test_limites(self):
        self.gravar([self.linha(),self.linha()])
        with self.assertRaises(ErroImportacao):self.processar(limite_linhas=1)
        with self.assertRaises(ErroImportacao):self.processar(limite_bytes=1)
    def test_sem_lista_ncm(self):
        self.gravar([self.linha()])
        with self.assertRaises(ErroImportacao):
            resumir_importacao_csv(self.arq,ncms=frozenset())
