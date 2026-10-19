import io
import unittest
from datetime import date

from nivon.anp_ppi import LayoutPPI, ErroPPI, ler_ppi_xlsx, comparar_ppi_com_produtor

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None


@unittest.skipIf(Workbook is None, "extras excel indisponível")
class TestAnpPpi(unittest.TestCase):
    def payload(self, *, cabeçalho="Itaqui (MA)"):
        wb = Workbook()
        ws = wb.active
        ws.title = "Diesel R$ semanal"
        ws.append(["Semana", cabeçalho])
        ws.append([date(2026, 10, 12), 4.10])
        bio = io.BytesIO()
        wb.save(bio)
        wb.close()
        return bio.getvalue()

    def layout(self):
        return LayoutPPI(aba="Diesel R$ semanal", produto="DIESEL_S10",
                         cabecalho_linha=1, coluna_data="Semana",
                         colunas_pontos={"ITAQUI": "Itaqui (MA)"})

    def extrair(self, payload):
        return ler_ppi_xlsx(
            payload, self.layout(), publicado_em="2026-10-19T09:00:00-03:00",
            coletado_em="2026-10-19T10:00:00-03:00",
            fonte_url="https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/arq-ppi/ppi.xlsx"
        )

    def test_xlsx_valido_gerar_observacao(self):
        rows = self.extrair(self.payload())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ponto_entrega"], "ITAQUI")
        self.assertEqual(rows[0]["data_referencia"], "2026-10-12")
        self.assertFalse(rows[0]["tributos_inclusos"])

    def test_layout_mudou_falha_fechado(self):
        with self.assertRaises(ErroPPI):
            self.extrair(self.payload(cabeçalho="Novo formato"))

    def test_mime_corrompido_nao_aceito(self):
        with self.assertRaises(ErroPPI):
            self.extrair(b"mau arquivo")

    def test_comparar_so_com_tributos_e_semana_coerentes(self):
        ppi = {"produto":"DIESEL_S10", "unidade":"BRL/L",
               "data_referencia":"2026-10-12", "preco_paridade":4.10}
        produtor = {"produto":"DIESEL_S10", "unidade":"BRL/L",
                    "data_referencia":"2026-10-12", "preco_produtor":4.80}
        with self.assertRaises(ErroPPI):
            comparar_ppi_com_produtor(ppi, produtor, imposto_federal_brl_unidade=None)
        result = comparar_ppi_com_produtor(ppi, produtor, imposto_federal_brl_unidade=0.50)
        self.assertAlmostEqual(result["spread_interno_menos_paridade"],0.20)
        self.assertTrue(result["nao_e_margem_de_lucro"])

    def test_semana_diferente_nao_compara(self):
        ppi={"produto":"DIESEL_S10", "unidade":"BRL/L", "data_referencia":"2026-10-12", "preco_paridade":4.10}
        produtor={"produto":"DIESEL_S10", "unidade":"BRL/L", "data_referencia":"2026-10-05", "preco_produtor":4.80}
        with self.assertRaises(ErroPPI):
            comparar_ppi_com_produtor(ppi, produtor, imposto_federal_brl_unidade=0.50)


if __name__=="__main__":
    unittest.main()
