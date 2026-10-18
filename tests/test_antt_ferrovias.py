import io
import zipfile
import unittest
from scripts.inspecionar_antt_ferrovias import resumo_zip


def livro_sintetico():
    data=io.BytesIO()
    with zipfile.ZipFile(data,"w") as z:
        z.writestr("xl/workbook.xml",
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets><sheet name="Rotas" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
          '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="dummy"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml",
          '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<dimension ref="A1:B2"/><sheetData>'
          '<row r="1"><c r="A1" t="inlineStr"><is><t>UF origem</t></is></c>'
          '<c r="B1" t="inlineStr"><is><t>UF destino</t></is></c></row>'
          '<row r="2"><c r="A2" t="inlineStr"><is><t>MT</t></is></c>'
          '<c r="B2" t="inlineStr"><is><t>GO</t></is></c></row>'
          '</sheetData></worksheet>')
    return data.getvalue()


class TestXLSXANTTFerroviario(unittest.TestCase):
    def test_inspecao_sintetica(self):
        r=resumo_zip(livro_sintetico())
        self.assertEqual(r["abas"][0]["aba"],"Rotas")
        self.assertEqual(r["abas"][0]["dimensao_declarada"],"A1:B2")
        self.assertEqual(r["abas"][0]["amostra_primeiras_linhas"][1][0]["valor"],"MT")

    def test_rejeita_arquivo_nao_xlsx(self):
        with self.assertRaises(zipfile.BadZipFile):
            resumo_zip(b"nao e xlsx")

    def test_rejeita_zip_sem_workbook(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,"w") as z:z.writestr("nao.txt","abc")
        with self.assertRaises(ValueError):
            resumo_zip(data.getvalue())

if __name__=="__main__":unittest.main()
