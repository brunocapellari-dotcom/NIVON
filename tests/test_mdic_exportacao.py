import tempfile
import unittest
from pathlib import Path
from nivon.mdic_exportacao import HEADER, ErroMDIC, resumir_exportacao_csv


class TestMDICExportacao(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.arq=Path(self.temp.name)/"EXP_2026.csv"

    def gerar(self,linhas):
        self.arq.write_text(";".join(HEADER)+"\n"+"\n".join(
            ";".join(str(v) for v in l) for l in linhas)+"\n",encoding="utf-8")

    def linha(self,*,ncm="12019000",kg="1000",usd="500",uf="MT",mes="09",pais="160"):
        return ["2026",mes,ncm,"10",pais,uf,"01","081",kg,usd,usd]

    def analisar(self):
        return resumir_exportacao_csv(self.arq,ncms=frozenset({"12019000"}))

    def test_conversao_quilos_para_toneladas_e_fob(self):
        self.gerar([self.linha()])
        r=self.analisar()
        self.assertEqual(r["recortes"][0]["toneladas"],1)
        self.assertEqual(r["recortes"][0]["valor_fob_usd"],500)
        self.assertEqual(r["recortes"][0]["valor_medio_usd_t"],500)
        self.assertTrue(r["recortes"][0]["nao_municipio"])

    def test_agrega_mesmo_recorte_sem_perder_detalhes(self):
        self.gerar([self.linha(kg="2000",usd="1000"),self.linha(kg="1000",usd="300")])
        r=self.analisar()
        self.assertEqual(r["recortes"][0]["toneladas"],3)
        self.assertEqual(r["recortes"][0]["linhas_agregadas"],2)
        self.assertEqual(r["recortes"][0]["valor_fob_usd"],1300)

    def test_pais_diferente_nao_e_somado_mesmo_recorte(self):
        self.gerar([self.linha(pais="160"),self.linha(pais="249")])
        self.assertEqual(len(self.analisar()["recortes"]),2)

    def test_ncm_outro_fica_fora_sem_inventar_total(self):
        self.gerar([self.linha(ncm="10059010"),self.linha()])
        r=self.analisar()
        self.assertEqual(r["registros_original"],2)
        self.assertEqual(r["registros_ncm_filtrados"],1)

    def test_ncm_ausente_rejeita_ao_inves_zero(self):
        self.gerar([self.linha(ncm="10059010")])
        with self.assertRaises(ErroMDIC):self.analisar()

    def test_cabecalho_diferente_rejeitado(self):
        self.arq.write_text("ANO;MES\n2026;09\n",encoding="utf-8")
        with self.assertRaises(ErroMDIC):self.analisar()

    def test_numero_negativo_rejeitado(self):
        self.gerar([self.linha(kg="-1")])
        with self.assertRaises(ErroMDIC):self.analisar()

    def test_mes_invalido_rejeitado(self):
        self.gerar([self.linha(mes="13")])
        with self.assertRaises(ErroMDIC):self.analisar()

    def test_kilo_zero_nao_gera_preco_medio_falso(self):
        self.gerar([self.linha(kg="0")])
        self.assertIsNone(self.analisar()["recortes"][0]["valor_medio_usd_t"])


if __name__=="__main__":
    unittest.main()
