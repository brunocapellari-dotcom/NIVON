import unittest
from nivon.balancos import Balanco, Proveniencia, reconciliar_balanco
from nivon.motores import DadoInvalido
from nivon.conab_catalogo import descobrir_planilhas, ErroCatalogoConab


class TestNovosBalancos(unittest.TestCase):
    def setUp(self):
        self.prov=Proveniencia(
            "FONTE_SINTETICA","INFORMADO","2025/2026",
            "2026-04-01","2026-05-01","2026-05-02T10:00:00Z","SAFRA")

    def balanco(self,produto,base_fisica=None):
        return Balanco(produto=produto,escopo="BRASIL",
            calendario="SAFRA",competencia="2025/2026",
            estoque_inicial_t=10,producao_t=100,importacao_t=0,
            entradas_interestaduais_t=0,consumo_domestico_t=20,
            exportacao_t=80,saidas_interestaduais_t=0,
            perdas_t=0,estoque_final_t=10,proveniencia=self.prov,
            base_fisica=base_fisica)

    def test_gergelim_balanco_toneladas(self):
        r=reconciliar_balanco(self.balanco("GERGELIM"))
        self.assertTrue(r["conciliado"])
        self.assertEqual(r["base_fisica"],"PESO_PRODUTO")

    def test_cana_balanco_toneladas_materia_prima(self):
        self.assertEqual(reconciliar_balanco(self.balanco("CANA"))["oferta_t"],110)

    def test_carne_bloqueia_cortes_sem_conversao(self):
        with self.assertRaises(DadoInvalido):
            self.balanco("CARNE_FRANGO")
        with self.assertRaises(DadoInvalido):
            self.balanco("CARNE_SUINA",base_fisica="PESO_PRODUTO")

    def test_carne_aceita_fluxos_mesma_base(self):
        for p in ("CARNE_FRANGO","CARNE_SUINA"):
            x=reconciliar_balanco(self.balanco(p,base_fisica="EQUIVALENTE_CARCACA"))
            self.assertTrue(x["conciliado"])
            self.assertEqual(x["base_fisica"],"EQUIVALENTE_CARCACA")

    def test_conab_gergelim_apenas_descobre_link_oficial(self):
        html='<a href="/conab/documento.xls">GergelimSerieHist.xls</a>'
        r=descobrir_planilhas(html,"GERGELIM")
        self.assertEqual(len(r),1)
        self.assertFalse(r[0]["coleta_habilitada"])
        self.assertIn("/gergelim",r[0]["pagina_publicacao"])

    def test_conab_gergelim_nao_confunde_soja(self):
        html='<a href="/conab/documento.xls">SojaSerieHist.xls</a>'
        with self.assertRaises(ErroCatalogoConab):
            descobrir_planilhas(html,"GERGELIM")


if __name__=="__main__":
    unittest.main()
