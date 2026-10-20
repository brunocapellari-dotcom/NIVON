import tempfile
import unittest
from pathlib import Path
from nivon.mdic_stream import processar_arquivo_anual,ErroStreamMDIC
from nivon.mdic_exportacao import HEADER as EXP
from nivon.mdic_importacao import COLUNAS as IMP
from nivon.mdic_municipios import CABECALHO as MUN

def linha(header,**kw):
    d=dict(CO_ANO="2026",CO_MES="09",CO_NCM="12019000",CO_UNID="10",CO_PAIS="160",
           SG_UF_NCM="MT",CO_VIA="01",CO_URF="081",QT_ESTAT="1",
           KG_LIQUIDO="2000",VL_FOB="800",VL_FRETE="80",VL_SEGURO="20",
           SH4="1201",SG_UF_MUN="MT",CO_MUN="5107925")
    d.update(kw)
    return ";".join(d[k] for k in header)

class TestMDICStream(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.dir=Path(t.name)
    def criar(self,filename,header,rows):
        p=self.dir/filename
        p.write_text(";".join(header)+"\n"+"\n".join(rows)+"\n",encoding="utf-8")
        return p
    def processar(self,p,*,direcao,granularidade,codigos,**kw):
        return processar_arquivo_anual(p,ano=2026,direcao=direcao,
              granularidade=granularidade,codigos=frozenset(codigos),
              coletado_em="2026-10-19T16:00:00Z",**kw)
    def test_exportacao_ncm_agrupa_e_nao_inventa_porto(self):
        p=self.criar("EXP_2026.csv",EXP,[linha(EXP),linha(EXP,CO_MES="08",KG_LIQUIDO="1000",VL_FOB="200")])
        r=self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"})
        self.assertEqual(r["linhas_total"],2);self.assertEqual(r["linhas_filtradas"],2)
        self.assertEqual(sum(x["kg"] for x in r["totais_arquivo_por_mes"]),3000)
        self.assertTrue(r["recortes"][0]["uf_nao_prova_municipio"])
        self.assertEqual(len(r["sha256_original"]),64)
    def test_importacao_cif_nao_e_valor_final(self):
        p=self.criar("IMP_2026.csv",IMP,[linha(IMP)])
        r=self.processar(p,direcao="IMPORTACAO",granularidade="NCM",codigos={"12019000"})
        x=r["recortes"][0]
        self.assertEqual((x["valor_fob_usd"],x["frete_internacional_usd"],x["seguro_internacional_usd"]),(800,80,20))
        self.assertEqual(r["totais_arquivo_por_mes"][0]["frete_seguro_internacional_usd"],100)
    def test_municipio_fiscal_que_nao_e_embarque(self):
        p=self.criar("EXP_2026_MUN.csv",MUN,[linha(MUN)])
        r=self.processar(p,direcao="EXPORTACAO",granularidade="MUNICIPIO_SH4",codigos={"1201"})
        x=r["recortes"][0];self.assertTrue(x["nao_origem_fisica"])
        self.assertEqual(x["codigo_municipio_fiscal"],"5107925")
    def test_importacao_mun_valida(self):
        p=self.criar("IMP_2026_MUN.csv",MUN,[linha(MUN)])
        r=self.processar(p,direcao="IMPORTACAO",granularidade="MUNICIPIO_SH4",codigos={"1201"})
        self.assertIsNone(r["recortes"][0]["frete_internacional_usd"])
    def test_totais_todos_codigos_separados_filtro(self):
        p=self.criar("EXP_2026.csv",EXP,[linha(EXP),linha(EXP,CO_NCM="31021010",KG_LIQUIDO="300")])
        r=self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"})
        self.assertEqual(r["linhas_total"],2)
        self.assertEqual(r["linhas_filtradas"],1)
        self.assertEqual(r["totais_arquivo_por_mes"][0]["kg"],2300)
    def test_ano_divergente_reprova(self):
        p=self.criar("EXP_2026.csv",EXP,[linha(EXP,CO_ANO="2025")])
        with self.assertRaises(ErroStreamMDIC):
            self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"})
    def test_sem_codigo_selecionado_nao_e_zero(self):
        p=self.criar("EXP_2026.csv",EXP,[linha(EXP)])
        with self.assertRaises(ErroStreamMDIC):
            self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"99999999"})
    def test_arquivo_falso_reprovado(self):
        p=self.criar("EXP_INVENTADO.csv",EXP,[linha(EXP)])
        with self.assertRaises(ErroStreamMDIC):
            self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"})
    def test_arquivo_com_header_errado_bloqueia(self):
        p=self.criar("EXP_2026.csv",EXP, [linha(EXP)])
        p.write_text("CO_ANO;CO_NCM\n2026;12019000\n")
        with self.assertRaises(ErroStreamMDIC):
            self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"})
    def test_limits_reprove_separadamente(self):
        p=self.criar("EXP_2026.csv",EXP,[linha(EXP),linha(EXP)])
        with self.assertRaises(ErroStreamMDIC):self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"},limite_linhas=1)
        with self.assertRaises(ErroStreamMDIC):self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"},limite_chaves=0)
        with self.assertRaises(ErroStreamMDIC):self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"},limite_bytes=1)
    def test_link_simbolico_reprovado(self):
        p=self.criar("EXP_2026.csv",EXP,[linha(EXP)])
        link=self.dir/"fake"/"EXP_2026.csv";link.parent.mkdir();link.symlink_to(p)
        with self.assertRaises(ErroStreamMDIC):
            self.processar(link,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"})
    def test_codigo_incorreto_tamanho_reprovado(self):
        p=self.criar("EXP_2026.csv",EXP,[linha(EXP)])
        with self.assertRaises(ErroStreamMDIC):
            self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"1201"})
    def test_linhas_mensais_mais_de_ano_reprovadas(self):
        p=self.criar("EXP_2026.csv",EXP,[linha(EXP,CO_MES="13")])
        with self.assertRaises(ErroStreamMDIC):
            self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"})
    def test_valores_negativos_e_nao_numericos(self):
        for kw in ({"KG_LIQUIDO":"-1"},{"VL_FOB":"abc"}):
            p=self.criar("EXP_2026.csv",EXP,[linha(EXP,**kw)])
            with self.assertRaises(ErroStreamMDIC):
                self.processar(p,direcao="EXPORTACAO",granularidade="NCM",codigos={"12019000"})
