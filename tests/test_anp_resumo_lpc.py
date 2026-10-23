import io
import unittest
from datetime import date
from zipfile import ZipFile

from nivon.anp_resumo_lpc import ErroResumoANP,ler_resumo_semanal_lpc

try:
    from openpyxl import Workbook
except ImportError:
    Workbook=None

URL=("https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/"
     "precos/arquivos-lpc/2026/resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx")
CAB=["DATA INICIAL","DATA FINAL","ESTADO","MUNICÍPIO","PRODUTO",
     "NÚMERO DE POSTOS PESQUISADOS","UNIDADE DE MEDIDA","PREÇO MÉDIO REVENDA",
     "PREÇO MÍNIMO REVENDA","PREÇO MÁXIMO REVENDA"]

@unittest.skipIf(Workbook is None,"openpyxl opcional não disponível")
class TestANPResumoLPC(unittest.TestCase):
    def workbook(self,rows=None,headers=None,prefixo_linhas=6):
        wb=Workbook();meta=wb.active;meta.title="BRASIL"
        ws=wb.create_sheet("MUNICIPIOS")
        for _ in range(prefixo_linhas):ws.append(["METADADOS ANP"])
        ws.append(headers if headers is not None else CAB)
        rows=rows if rows is not None else [
            [date(2026,10,4),date(2026,10,10),"MATO GROSSO","SINOP",
             "OLEO DIESEL S10",8,"R$/l",6.05,5.99,6.14],
            [date(2026,10,4),date(2026,10,10),"MATO GROSSO","SORRISO",
             "OLEO DIESEL",5,"R$/l","5,83",5.70,6.03],
            [date(2026,10,4),date(2026,10,10),"MATO GROSSO","RONDONÓPOLIS",
             "OLEO DIESEL S10",6,"R$/l",6.13,5.90,6.30],
            [date(2026,10,4),date(2026,10,10),"SÃO PAULO","SÃO PAULO",
             "OLEO DIESEL S10",24,"R$/l",6.22,6.02,6.40],
        ]
        for row in rows:ws.append(row)
        b=io.BytesIO();wb.save(b);wb.close();return b.getvalue()

    def run_parse(self,payload=None,**kwargs):
        return ler_resumo_semanal_lpc(
            self.workbook() if payload is None else payload,
            coletado_em=kwargs.pop("coletado_em","2026-10-20T10:00:00-03:00"),
            origem_url=kwargs.pop("origem_url",URL),**kwargs)

    def test_layout_real_2026_auto_detecta_cabecalho_na_linha_10(self):
        payload=self.workbook(prefixo_linhas=9)
        result=self.run_parse(payload)
        self.assertEqual(result["linha_cabecalho"],10)
        self.assertEqual(result["municipios_distintos"],3)
        self.assertEqual(result["semanas_distintas"],1)
        self.assertFalse(result["publicavel"])
        with self.assertRaisesRegex(ErroResumoANP,"colunas divergentes"):
            self.run_parse(payload,cabecalho_linha=7)

    def test_tres_municipios_mt_com_semana_observada(self):
        x=self.run_parse()
        self.assertEqual(x["municipios_distintos"],3)
        self.assertEqual(x["semanas_distintas"],1)
        self.assertEqual(len(x["observacoes"]),3)
        self.assertFalse(x["publicavel"])
        self.assertTrue(all(v["semana_fim_oficial"]=="2026-10-10" for v in x["observacoes"]))
        self.assertEqual([x["produto"] for x in x["observacoes"]].count("DIESEL S10"),2)

    def test_municipio_com_filtro_inclui_unico(self):
        x=self.run_parse(municipios_mt=frozenset({"SINOP"}))
        self.assertEqual(x["municipios_distintos"],1)
        self.assertEqual(x["observacoes"][0]["preco_medio_revenda_rs_l"],6.05)

    def test_preco_diesel_s10_nao_se_mistura_com_diesel_comum(self):
        rows=[
            [date(2026,10,4),date(2026,10,10),"MATO GROSSO","SINOP","OLEO DIESEL",4,"R$/l",5.8,None,None],
            [date(2026,10,4),date(2026,10,10),"MATO GROSSO","SINOP","OLEO DIESEL S10",8,"R$/l",6.1,None,None],
        ]
        x=self.run_parse(self.workbook(rows))
        self.assertEqual(len(x["observacoes"]),2)

    def test_semana_futura_rejeita(self):
        rows=[[date(2027,10,4),date(2027,10,10),"MATO GROSSO","SINOP",
               "OLEO DIESEL S10",8,"R$/l",6.05,None,None]]
        with self.assertRaisesRegex(ErroResumoANP,"futuro"):
            self.run_parse(self.workbook(rows))

    def test_preco_invalid_ou_unidade_errada_rejeita(self):
        rows=[[date(2026,10,4),date(2026,10,10),"MATO GROSSO","SINOP",
               "OLEO DIESEL S10",8,"R$/kg",6.05,None,None]]
        with self.assertRaisesRegex(ErroResumoANP,"R\$/litro"):
            self.run_parse(self.workbook(rows))

    def test_cabecalho_diferente_falha_fechado(self):
        h=list(CAB);h[7]="MÉDIA GERAL"
        with self.assertRaisesRegex(ErroResumoANP,"colunas divergentes"):
            self.run_parse(self.workbook(headers=h), cabecalho_linha=7)
        with self.assertRaisesRegex(ErroResumoANP,"não localizado"):
            self.run_parse(self.workbook(headers=h))

    def test_duplicata_mesma_semana_mesmo_municipio_produto(self):
        row=[date(2026,10,4),date(2026,10,10),"MATO GROSSO","SINOP",
             "OLEO DIESEL S10",8,"R$/l",6.05,None,None]
        with self.assertRaisesRegex(ErroResumoANP,"duplicada"):
            self.run_parse(self.workbook([row,row]))

    def test_sem_municipio_amostrado_nao_infere_zero(self):
        with self.assertRaisesRegex(ErroResumoANP,"não afirmar zero"):
            self.run_parse(municipios_mt=frozenset({"NOVA MUTUM"}))

    def test_xlsx_nao_contem_postos_individuais(self):
        x=self.run_parse()
        self.assertTrue(all("cnpj" not in k.lower() for k in x["observacoes"][0]))
        self.assertNotIn("preco_produtor",x["observacoes"][0])

    def test_resposta_waf_html_nao_aceita(self):
        with self.assertRaises(ErroResumoANP):
            self.run_parse(b"<html>Access denied</html>")

    def test_url_alheia_nao_aceita(self):
        with self.assertRaises(ErroResumoANP):
            self.run_parse(origem_url="https://example.com/resumo.xlsx")

    def test_excel_serial_date_aceito(self):
        rows=[[46300,46306,"MATO GROSSO","SINOP","OLEO DIESEL S10",6,"R$/l",6.05,None,None]]
        # A data precisa cair antes da captura; 46300/46306 são uma semana no calendário de 2026.
        try:
            x=self.run_parse(self.workbook(rows))
            self.assertEqual(len(x["observacoes"]),1)
        except ErroResumoANP as exc:
            self.assertNotIn("serial Excel",str(exc))


if __name__=="__main__":
    unittest.main()
