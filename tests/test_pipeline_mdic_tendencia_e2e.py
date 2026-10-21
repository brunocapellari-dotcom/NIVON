"""E2E de tendência MDIC: CSV anual -> SQLite -> série com vintages -> YoY.

Arquivos inteiramente sintéticos; a saída jamais é um sinal comercial válido.
"""
import tempfile
import unittest
from pathlib import Path

from nivon.mdic_exportacao import HEADER
from nivon.ingestao_mdic import ingerir_arquivo_mdic
from nivon.registro_snapshots import abrir_registro
from nivon.series_mdic_modelos import montar_serie_mdic,ErroSerieMDIC
from nivon.tendencias_mdic import classificar_tendencia_mdic

CAT={"datasets":[{"id":"MDIC_COMEX_NCM","source_id":"MDIC",
                  "enabled":False,"collection_authorized":False}]}
def criar_csv(root,ano,fator=1.0,meses=range(1,13)):
    path=root/f"EXP_{ano}.csv"
    values=[]
    for mes in meses:
        row={"CO_ANO":str(ano),"CO_MES":str(mes),"CO_NCM":"12019000",
             "CO_UNID":"10","CO_PAIS":"160","SG_UF_NCM":"MT",
             "CO_VIA":"01","CO_URF":"081","QT_ESTAT":"1",
             "KG_LIQUIDO":str(int(mes*100*fator)),
             "VL_FOB":str(int(mes*500*fator))}
        values.append(";".join(row[f] for f in HEADER))
    path.write_text(";".join(HEADER)+"\n"+"\n".join(values)+"\n",encoding="utf-8")
    return path

class TestCSVParaTendencia(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)
    def gravar(self,ano,fator=1.0,meses=range(1,13)):
        path=criar_csv(self.root,ano,fator,meses)
        return ingerir_arquivo_mdic(
            self.db,CAT,caminho=path,ano=ano,
            direcao="EXPORTACAO",granularidade="NCM",
            codigos=frozenset({"12019000"}),
            coletado_em="2026-10-20T15:00:00Z")
    def serie(self,**kw):
        return montar_serie_mdic(self.db,ano_inicial=2024,ano_final=2025,
            direcao="EXPORTACAO",granularidade="NCM",
            codigo_produto="12019000",uf="MT",
            variavel="PESO_LIQUIDO_KG",
            corte_coleta=kw.pop("corte_coleta","2026-10-20T16:00:00Z"),
            incluir_sinteticos=kw.pop("incluir_sinteticos",True))
    def test_serie_reconciliavel_com_snapshots_e_tendencia_alta(self):
        a=self.gravar(2024);b=self.gravar(2025,1.20)
        preparado=self.serie()
        self.assertEqual([x["sha256"] for x in preparado["vintages"]],
                         [a["sha256"],b["sha256"]])
        r=classificar_tendencia_mdic(preparado,
                 permitir_sinteticos_para_teste=True)
        self.assertEqual(r["tendencia"],"ALTA")
        self.assertAlmostEqual(r["mediana_yoy_pct"],20.0)
        self.assertFalse(r["homologado"])
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["fluxo_fisico_ou_frete_inferido"])
    def test_historico_igual_tendencia_estavel(self):
        self.gravar(2024);self.gravar(2025)
        r=classificar_tendencia_mdic(self.serie(),
            permitir_sinteticos_para_teste=True)
        self.assertEqual(r["tendencia"],"ESTABILIDADE")
    def test_mes_faltante_impede_classificacao(self):
        self.gravar(2024)
        self.gravar(2025,1.20,meses=range(1,12))
        with self.assertRaises(ErroSerieMDIC):
            self.serie()
    def test_corte_antes_do_ingresso_bloqueia(self):
        self.gravar(2024);self.gravar(2025)
        with self.assertRaises(ErroSerieMDIC):
            self.serie(corte_coleta="2026-10-19T12:00:00Z")
    def test_sem_sinteticos_na_via_padrao(self):
        self.gravar(2024);self.gravar(2025)
        with self.assertRaises(ErroSerieMDIC):
            self.serie(incluir_sinteticos=False)
