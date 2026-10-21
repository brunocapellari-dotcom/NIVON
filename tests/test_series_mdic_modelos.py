import tempfile
import unittest
from pathlib import Path

from nivon.registro_snapshots import abrir_registro
from nivon.ingestao_mdic import ingerir_arquivo_mdic
from nivon.mdic_exportacao import HEADER
from nivon.series_mdic_modelos import (montar_serie_mdic,
                                      avaliar_cenario_mensal_mdic,ErroSerieMDIC)
CAT={"datasets":[{"id":"MDIC_COMEX_NCM","source_id":"MDIC",
                  "enabled":False,"collection_authorized":False}]}
def dados_mes(ano,mes,cod="12019000",uf="MT",valor="800"):
    cols=dict(CO_ANO=str(ano),CO_MES=str(mes),CO_NCM=cod,CO_UNID="10",
              CO_PAIS="160",SG_UF_NCM=uf,CO_VIA="01",CO_URF="081",
              QT_ESTAT="1",KG_LIQUIDO=str(mes*100),VL_FOB=valor)
    return ";".join(cols[x] for x in HEADER)
class TestSerieMDICParaMotores(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.db=abrir_registro(":memory:");self.addCleanup(self.db.close)
    def ano(self,ano,meses=range(1,13),cod="12019000",uf="MT",
            coleta="2026-10-20T12:00:00Z", **extra):
        p=self.root/f"EXP_{ano}.csv"
        p.write_text(";".join(HEADER)+"\n"+
                     "\n".join(dados_mes(ano,m,cod,uf) for m in meses)+"\n",encoding="utf-8")
        return ingerir_arquivo_mdic(self.db,CAT,caminho=p,
            ano=ano,direcao="EXPORTACAO",granularidade="NCM",
            codigos=frozenset(extra.pop("codigos",{"12019000",cod})),
            coletado_em=coleta,**extra)
    def duas(self):
        self.ano(2024);self.ano(2025)
    def montar(self,**kw):
        return montar_serie_mdic(self.db,ano_inicial=2024,ano_final=2025,
               direcao="EXPORTACAO",granularidade="NCM",
               codigo_produto=kw.pop("codigo_produto","12019000"),
               uf=kw.pop("uf","MT"),variavel=kw.pop("variavel","PESO_LIQUIDO_KG"),
               corte_coleta=kw.pop("corte_coleta","2026-10-20T13:00:00Z"),
               incluir_sinteticos=kw.pop("incluir_sinteticos",True),**kw)
    def test_24_meses_fiscais_com_sha_por_ano(self):
        self.duas()
        x=self.montar()
        self.assertEqual(x["contagem_meses"],24)
        self.assertEqual(x["serie"][0],("2024-01",100.0))
        self.assertEqual(x["serie"][-1],("2025-12",1200.0))
        self.assertEqual(len(x["vintages"]),2)
        self.assertFalse(x["apta_publicacao_preditiva"])
    def test_padrao_sem_sinteticos_rejeita_fonte(self):
        self.duas()
        with self.assertRaises(ErroSerieMDIC):
            self.montar(incluir_sinteticos=False)
    def test_filtro_produto_nao_observado_reprova(self):
        self.duas()
        with self.assertRaises(ErroSerieMDIC):
            self.montar(codigo_produto="31021010")
    def test_lacuna_de_mes_nao_e_zero(self):
        self.ano(2024);self.ano(2025,meses=[m for m in range(1,13) if m!=6])
        with self.assertRaisesRegex(ErroSerieMDIC,"12 meses"):
            self.montar()
    def test_fonte_completa_mas_produto_falta_em_um_mes(self):
        self.ano(2024);self.ano(2025)
        # dados de 2025 só cobrem outro código para dezembro em edição revisada
        p=self.root/"EXP_2025.csv"
        linhas=[";".join(HEADER)]
        for m in range(1,13):
            linhas.append(dados_mes(2025,m,"31021010" if m==12 else "12019000"))
        p.write_text("\n".join(linhas)+"\n")
        self.ano_sem_sobrescrever(p,2025,coleta="2026-10-20T12:30:00Z")
        with self.assertRaisesRegex(ErroSerieMDIC,"mês sem produto"):
            self.montar()
    def ano_sem_sobrescrever(self,p,ano,coleta):
        return ingerir_arquivo_mdic(self.db,CAT,caminho=p,ano=ano,
            direcao="EXPORTACAO",granularidade="NCM",
            codigos=frozenset({"12019000","31021010"}),coletado_em=coleta)
    def test_corte_antes_de_coleta_impede_uso(self):
        self.duas()
        with self.assertRaises(ErroSerieMDIC):
            self.montar(corte_coleta="2026-10-19T00:00:00Z")
    def test_uf_nao_e_pais_e_nao_inventa_estado(self):
        self.duas()
        with self.assertRaises(ErroSerieMDIC):
            self.montar(uf="BR")
        with self.assertRaises(ErroSerieMDIC):
            self.montar(uf="SP")
    def test_unidade_usd_explicita(self):
        self.duas()
        x=self.montar(variavel="VALOR_FOB_USD")
        self.assertEqual(x["unidade"],"USD")
        self.assertEqual(x["serie"][0],("2024-01",800.0))
    def test_cenario_sintetico_exige_optin_e_nao_publica(self):
        self.duas()
        serie=self.montar()
        def backend(x,h):return [900.0]*h
        with self.assertRaises(PermissionError):
            avaliar_cenario_mensal_mdic(serie,backend=backend,horizonte=2)
        r=avaliar_cenario_mensal_mdic(serie,backend=backend,horizonte=2,
                                      permitir_sinteticos_para_teste=True)
        self.assertEqual(len(r["previsoes"]),2)
        self.assertFalse(r["publicavel"])
        self.assertEqual(r["unidade"],"kg")
    def test_falsa_homologacao_nao_libera(self):
        self.duas()
        s=self.montar();s["apta_publicacao_preditiva"]=True
        with self.assertRaises(ErroSerieMDIC):
            avaliar_cenario_mensal_mdic(s,backend=lambda x,h:[100]*h,
                                         permitir_sinteticos_para_teste=True)
    def test_ano_unico_rejeitado(self):
        self.ano(2025)
        with self.assertRaises(ErroSerieMDIC):
            montar_serie_mdic(self.db,ano_inicial=2025,ano_final=2025,
               direcao="EXPORTACAO",granularidade="NCM",codigo_produto="12019000",
               uf="MT",variavel="PESO_LIQUIDO_KG",corte_coleta="2026-10-20T13:00:00Z",
               incluir_sinteticos=True)
