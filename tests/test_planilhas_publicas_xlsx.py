"""Fixtures OOXML reais construídas em memória, sem dependência de openpyxl."""
import io
import zipfile
import unittest
from datetime import datetime, timezone
from nivon.planilhas_publicas_xlsx import (
    URLS, ErroPlanilhaPublica, normalizar_planilha, consultar_planilha,
)

RID = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/package/2006/relationships"
NOW = datetime(2026, 10, 21, 16, tzinfo=timezone.utc)


def arquivo_zip(*, nome_planilha="Dados", unsafe=False, extlinks=False):
    wb = (f'<workbook xmlns="{M}" xmlns:r="{RID}"><sheets>'
          f'<sheet name="{nome_planilha}" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = (f'<Relationships xmlns="{R}"><Relationship Id="rId1" '
            f'Type="{RID}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    ws = (f'<worksheet xmlns="{M}"><sheetData>'
          '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
          '<row r="2"><c r="A2" t="inlineStr"><is><t>2026-10-01</t></is></c>'
          '<c r="B2"><v>6.35</v></c></row>'
          '<row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3">'
          '<f>1+1</f><v>2</v></c></row>'
          '</sheetData></worksheet>')
    shared = (f'<sst xmlns="{M}"><si><t>Date</t></si><si><t>Unit price</t></si>'
              '<si><t>Footer</t></si></sst>')
    paths = {
        "[Content_Types].xml": "<Types/>",
        "xl/workbook.xml": wb,
        "xl/_rels/workbook.xml.rels": rels,
        "xl/worksheets/sheet1.xml": ws,
        "xl/sharedStrings.xml": shared,
    }
    if extlinks:
        paths["xl/externalLinks/externalLink1.xml"] = "<externalLink/>"
    if unsafe:
        paths["../config/private.txt"] = "do not open"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in paths.items():
            z.writestr(k, v)
    return b.getvalue()


class Resp:
    status = 200
    headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    def __init__(self, url, body): self.url, self.body=url, body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def geturl(self): return self.url
    def read(self, n): return self.body[:n]


class Abridor:
    def __init__(self, blob): self.blob, self.urls=blob, []
    def open(self, req, timeout):
        self.urls.append(req.full_url)
        return Resp(req.full_url, self.blob)


class TestPublicXLSX(unittest.TestCase):
    def test_três_fontes_sem_chave_e_sem_formulas_avaliadas(self):
        for ds, url in URLS.items():
            with self.subTest(dataset=ds):
                item = normalizar_planilha(arquivo_zip(), dataset_id=ds,
                                           coletado_em="2026-10-21T12:00:00-04:00")
                self.assertEqual(item["url"], url)
                self.assertEqual(item["abas"][0]["n_linhas"], 3)
                self.assertEqual(item["abas"][0]["linhas"][1]["celulas"], ["2026-10-01", "6.35"])
                self.assertIsNone(item["abas"][0]["linhas"][2]["celulas"][1])
                self.assertFalse(item["valores_monetarios_publicaveis"])
                self.assertFalse(item["unidades_e_vigencia_homologadas"])
                self.assertEqual(len(item["sha256_original"]), 64)
                self.assertEqual(item["coleta"], "2026-10-21T16:00:00+00:00")

    def test_download_explicitamente_uma_vez(self):
        a = Abridor(arquivo_zip())
        with self.assertRaises(PermissionError):
            consultar_planilha(dataset_id="WB_PINK_SHEET_COMMODITIES", abridor=a)
        self.assertEqual(a.urls, [])
        d = consultar_planilha(dataset_id="WB_PINK_SHEET_COMMODITIES",
                              executar=True, abridor=a, instante=NOW)
        self.assertEqual(a.urls, [URLS["WB_PINK_SHEET_COMMODITIES"]])
        self.assertEqual(d["dados"]["dataset_id"], "WB_PINK_SHEET_COMMODITIES")

    def test_zip_inseguro_e_conexoes_externas_recusados(self):
        for blob in (arquivo_zip(unsafe=True), arquivo_zip(extlinks=True),
                     b"xxx", b"", b"PK\x03\x04"):
            with self.subTest(length=len(blob)), self.assertRaises(ErroPlanilhaPublica):
                normalizar_planilha(blob, dataset_id="WB_PINK_SHEET_COMMODITIES",
                                   coletado_em="2026-10-21T16:00:00Z")

    def test_schema_invalido_ou_dataset_desconhecido(self):
        with self.assertRaises(ErroPlanilhaPublica):
            normalizar_planilha(arquivo_zip(), dataset_id="NIVON_FAKE",
                                coletado_em="2026-10-21T16:00:00Z")
        with self.assertRaises(ErroPlanilhaPublica):
            normalizar_planilha(arquivo_zip(), dataset_id="WB_PINK_SHEET_COMMODITIES",
                                coletado_em="2026-10-21T16:00:00")


if __name__ == "__main__":
    unittest.main()
