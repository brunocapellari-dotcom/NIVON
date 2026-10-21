import io
import unittest
from datetime import date

from nivon.anp_semanal_municipios import (
    ErroANPSemanal,LayoutSemanalANP,interpretar_anp_semanal_xlsx
)

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None

TITULOS=["UF","MUNICÍPIO","PRODUTO","DATA INÍCIO","DATA FIM",
         "PREÇO MÉDIO VENDA","NÚMERO POSTOS"]


@unittest.skipIf(Workbook is None,"openpyxl opcional não instalado")
class TestANPSemanalMunicipios(unittest.TestCase):
    def layout(self,**changes):
        x={"aba":"Dados 2026","cabecalho_linha":1,
            "colunas":{"uf":"UF","municipio":"MUNICÍPIO","produto":"PRODUTO",
                       "semana_inicio":"DATA INÍCIO","semana_fim":"DATA FIM",
                       "preco_medio":"PREÇO MÉDIO VENDA","postos":"NÚMERO POSTOS"},
            "documento_schema":"FIXTURE_SINTETICA_20261020",
            "unidade_preco":"BRL/L"}
        x.update(changes)
        return LayoutSemanalANP(**x)

    def arquivo(self,linhas=None,header=None):
        wb=Workbook()
        w=wb.active;w.title="Dados 2026"
        w.append(header if header is not None else TITULOS)
        if linhas is None:
            linhas=[
               ["MT","SINOP","DIESEL S10",date(2026,10,11),
                date(2026,10,17),5.79,8],
               ["MT","SORRISO","DIESEL S10",date(2026,10,11),
                date(2026,10,17),"5,85",5],
               ["MT","RONDONÓPOLIS","DIESEL",date(2026,10,11),
                date(2026,10,17),5.53,6],
               ["PR","CURITIBA","DIESEL S10",date(2026,10,11),
                date(2026,10,17),6.04,15],
            ]
        for row in linhas:w.append(row)
        data=io.BytesIO();wb.save(data);wb.close()
        return data.getvalue()

    def parse(self,data=None,**kwargs):
        return interpretar_anp_semanal_xlsx(
            data if data is not None else self.arquivo(),
            layout=kwargs.pop("layout",self.layout()),
            coletado_em=kwargs.pop("coletado_em","2026-10-20T09:00:00-03:00"),
            ano_esperado=kwargs.pop("ano_esperado",2026),**kwargs)

    def test_3_municipios_semana_oficial_sem_inferir(self):
        v=self.parse()
        self.assertEqual(len(v["observacoes"]),3)
        self.assertEqual(v["origem"],"XLSX_SEMANAL_NAO_CSV_MENSAL")
        self.assertTrue(all(x["semana_inicio_oficial"]=="2026-10-11" for x in v["observacoes"]))
        self.assertTrue(all(x["semana_fim_oficial"]=="2026-10-17" for x in v["observacoes"]))
        self.assertEqual(v["cobertura_municipal"],["RONDONÓPOLIS","SINOP","SORRISO"])
        self.assertFalse(v["publicacao_autorizada"])
        self.assertEqual({(r["municipio"],r["preco_medio_revenda_rs_l"]) for r in v["observacoes"]},
                         {("SINOP",5.79),("SORRISO",5.85),("RONDONÓPOLIS",5.53)})

    def test_sem_municipio_nao_e_zero(self):
        row=[["MT","CUIABÁ","DIESEL S10",date(2026,10,11),
               date(2026,10,17),5.80,15]]
        with self.assertRaisesRegex(ErroANPSemanal,"nenhum município"):
            self.parse(self.arquivo(row))

    def test_inversao_data_ou_sete_dias_incorretos(self):
        row=[["MT","SINOP","DIESEL S10",date(2026,10,12),
               date(2026,10,17),5.80,10]]
        with self.assertRaisesRegex(ErroANPSemanal,"7 dias"):
            self.parse(self.arquivo(row))

    def test_produto_diesel_s10_distinto_diesel(self):
        row=[
            ["MT","SINOP","DIESEL S10",date(2026,10,11),date(2026,10,17),5.90,10],
            ["MT","SINOP","DIESEL",date(2026,10,11),date(2026,10,17),5.80,11],
        ]
        v=self.parse(self.arquivo(row))
        self.assertEqual(len(v["observacoes"]),2)

    def test_planilha_cabecalho_alterado_falha_fechado(self):
        cab=["UF","MUNICÍPIO","PRODUTO","DATA INÍCIO","DATA FIM",
             "VALOR ATUALIZADO","NÚMERO POSTOS"]
        with self.assertRaisesRegex(ErroANPSemanal,"cabeçalho"):
            self.parse(self.arquivo(header=cab))

    def test_preco_ou_postos_invalidos_rejeita(self):
        row=[["MT","SORRISO","DIESEL S10",date(2026,10,11),
               date(2026,10,17),0,0]]
        with self.assertRaises(ErroANPSemanal):
            self.parse(self.arquivo(row))

    def test_csv_ou_html_injetado_nao_e_excel(self):
        with self.assertRaises(ErroANPSemanal):
            self.parse(b"<html>WAF response</html>")

    def test_sem_layout_nao_aprova(self):
        with self.assertRaises(ErroANPSemanal):
            interpretar_anp_semanal_xlsx(self.arquivo(),layout=None,
                                         coletado_em="2026-10-20T09:00:00-03:00")

    def test_duplicata_no_arquivo_rejeita(self):
        row=["MT","SORRISO","DIESEL S10",date(2026,10,11),
             date(2026,10,17),5.90,9]
        with self.assertRaisesRegex(ErroANPSemanal,"duplicada"):
            self.parse(self.arquivo([row,row]))

    def test_sintetico_nao_indica_homologacao_real(self):
        r=self.parse()
        self.assertEqual(r["documento_layout"],"FIXTURE_SINTETICA_20261020")
        self.assertFalse(r["publicacao_autorizada"])


if __name__=="__main__":
    unittest.main()
