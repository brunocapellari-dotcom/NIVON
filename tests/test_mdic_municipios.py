import tempfile
import unittest
from pathlib import Path

from nivon.mdic_municipios import (CABECALHO, ErroMDICMunicipios,
                                   resumir_municipios_sh4)


class TestMDICMunicipal(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.f=Path(self.d.name)/"EXP_2026_MUN.csv"

    def linha(self, **p):
        x=dict(CO_ANO="2026",CO_MES="09",SH4="1201",CO_PAIS="160",
               SG_UF_MUN="MT",CO_MUN="5105259",KG_LIQUIDO="2000",VL_FOB="1000")
        x.update(p)
        return ";".join(x[k] for k in CABECALHO)

    def gravar(self,linhas):
        self.f.write_text(";".join(CABECALHO)+"\n"+"\n".join(linhas)+"\n",encoding="utf-8")

    def processar(self,**params):
        return resumir_municipios_sh4(self.f,direcao="EXPORTACAO",
                                      posicoes_sh4=frozenset({"1201"}),**params)

    def test_soja_municipio_fiscal_distinto_de_origem_do_produto(self):
        self.gravar([self.linha()])
        r=self.processar()
        self.assertEqual(r["recortes"][0]["codigo_municipio_declarado"],"5105259")
        self.assertTrue(r["recortes"][0]["codigo_ibge_nao_validado"])
        self.assertIn("domicilio fiscal",r["limite_semantico"])
        self.assertEqual(r["recortes"][0]["toneladas"],2)
        self.assertEqual(r["recortes"][0]["valor_fob_usd"],1000)

    def test_importacao_e_exportacao_sao_distintas(self):
        self.gravar([self.linha()])
        x=resumir_municipios_sh4(self.f,direcao="IMPORTACAO",posicoes_sh4=frozenset({"1201"}))
        self.assertEqual(x["direcao"],"IMPORTACAO")

    def test_agregacao_mesma_chave(self):
        self.gravar([self.linha(),self.linha(KG_LIQUIDO="3000",VL_FOB="2000")])
        r=self.processar()
        self.assertEqual(r["recortes"][0]["peso_kg"],5000)
        self.assertEqual(r["recortes"][0]["linhas_agregadas"],2)

    def test_municipios_e_paises_distintos(self):
        self.gravar([self.linha(), self.linha(CO_MUN="5107925"),self.linha(CO_PAIS="249")])
        self.assertEqual(len(self.processar()["recortes"]),3)

    def test_sh4_nao_informa_ncm(self):
        self.gravar([self.linha(SH4="12019000")])
        with self.assertRaises(ErroMDICMunicipios): self.processar()

    def test_sem_sh4_filtrado_nao_inventa_zero(self):
        self.gravar([self.linha(SH4="1005")])
        with self.assertRaises(ErroMDICMunicipios): self.processar()

    def test_schema_alterado_bloqueia(self):
        self.f.write_text("CO_ANO;SH4\n2026;1201\n")
        with self.assertRaises(ErroMDICMunicipios): self.processar()

    def test_fob_negativo_bloqueia(self):
        self.gravar([self.linha(VL_FOB="-10")])
        with self.assertRaises(ErroMDICMunicipios): self.processar()

    def test_mes_invalido_bloqueia(self):
        self.gravar([self.linha(CO_MES="13")])
        with self.assertRaises(ErroMDICMunicipios): self.processar()

    def test_limite_e_fonte_protegida(self):
        self.gravar([self.linha(),self.linha()])
        with self.assertRaises(ErroMDICMunicipios): self.processar(limite_linhas=1)
        with self.assertRaises(ErroMDICMunicipios): self.processar(limite_bytes=1)
        link=Path(self.d.name)/"link.csv"
        link.symlink_to(self.f)
        with self.assertRaises(ErroMDICMunicipios):
            resumir_municipios_sh4(link,direcao="EXPORTACAO",posicoes_sh4=frozenset({"1201"}))

    def test_schema_SH4_e_hash(self):
        self.gravar([self.linha()])
        self.assertEqual(len(self.processar()["sha256_original"]),64)
        self.assertEqual(set(self.processar()["recortes"][0]),{
            "competencia","sh4","uf_domicilio_fiscal","codigo_municipio_declarado",
            "pais","uf_brasileira","codigo_ibge_nao_validado","peso_kg","toneladas",
            "valor_fob_usd","valor_medio_usd_t","linhas_agregadas","natureza"})
