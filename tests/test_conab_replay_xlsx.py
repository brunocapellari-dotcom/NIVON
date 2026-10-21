"""CONAB XLSX: fixture pública agrobr, OCR-free, offline, sem publicação."""
import base64
import hashlib
import io
import unittest
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

from nivon.conab_replay_xlsx import reexecutar_xlsx_conab,ErroXlsxProgresso,PARSER_ID

BASE = Path(__file__).parent/"fixtures"/"conab_progresso_agrobr_20260207.xlsx.b64"
URL = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture-terceiro"
CAPTURE = "2026-02-24T09:59:00+00:00"


def workbook():
    return base64.b64decode(BASE.read_text(encoding="ascii").strip(),validate=True)


def run(data=None, **kw):
    data=workbook() if data is None else data
    return reexecutar_xlsx_conab(data,sha256_origem=kw.get("hash",hashlib.sha256(data).hexdigest()),
            url_origem=kw.get("url",URL),coletado_em=kw.get("coleta",CAPTURE),
            publicado_em=kw.get("publicacao",None))


class TestProgressoXlsxGolden(unittest.TestCase):
    def test_golden_do_agrobr_contrato_11_registros(self):
        v=run()
        self.assertEqual(v["parser_id"],PARSER_ID)
        self.assertEqual(v["observacoes"],11)
        self.assertFalse(v["migracao_permitida"])
        self.assertFalse(v["direitos_de_uso_verificados"])
        self.assertTrue(v["arquivo_de_terceiro_sem_prova_de_origem"])
        self.assertEqual(v["raw_sha256"],hashlib.sha256(workbook()).hexdigest())
        rows=[__import__("json").loads(x) for x in v["mapa_semantico"].values()]
        self.assertEqual(set(x["uf"] for x in rows),{"GO","MT","PR","MEDIA_ESTADOS"})
        self.assertEqual(set(x["operacao"] for x in rows),{"Colheita","Semeadura"})
        self.assertEqual(set(x["cultura"] for x in rows),{"Soja","Milho 2ª"})
        self.assertEqual(set(x["competencia"] for x in rows),{"2026-02-07"})
        self.assertEqual(set(x["safra"] for x in rows),{"2025/26"})
        self.assertEqual(len([x for x in rows if x["cultura"]=="Soja" and x["operacao"]=="Colheita"]),4)
        self.assertEqual(len([x for x in rows if x["cultura"]=="Soja" and x["operacao"]=="Semeadura"]),4)
        self.assertEqual(len([x for x in rows if x["cultura"]=="Milho 2ª" and x["operacao"]=="Semeadura"]),3)
        value=next(x["pct_semana_atual"] for x in rows
                    if x["cultura"]=="Soja" and x["operacao"]=="Colheita" and x["uf"]=="MT")
        self.assertAlmostEqual(value,0.468)

    def test_repetir_bytes_gera_mesmo_mapa(self):
        a=run()
        b=run()
        self.assertEqual(a["mapa_semantico"],b["mapa_semantico"])

    def test_hash_raw_divergente_recusado(self):
        with self.assertRaises(ErroXlsxProgresso):
            run(hash="0"*64)

    def test_mudar_bytes_e_reutilizar_hash_antigo_recusado(self):
        raw=workbook()
        with self.assertRaises(ErroXlsxProgresso):
            run(raw+b"!",hash=hashlib.sha256(raw).hexdigest())

    def test_nao_trata_pdf_como_xlsx(self):
        with self.assertRaises(ErroXlsxProgresso):
            run(b"%PDF-1.4\n")

    def test_html_disfarcado_recusado(self):
        with self.assertRaises(ErroXlsxProgresso):
            run(b"<!doctype html>bloqueio")

    def test_coleta_sem_fuso_recusada(self):
        with self.assertRaises(ErroXlsxProgresso):
            run(coleta="2026-02-24T09:59:00")

    def test_publicacao_futura_recusada(self):
        with self.assertRaises(ErroXlsxProgresso):
            run(publicacao="2026-03-01T00:00:00Z")

    def test_publicacao_desconhecida_permanece_null(self):
        x=run()
        self.assertFalse(x["publicacao_extraida_do_xlsx"])
        self.assertTrue(all('"publicacao":null' in row for row in x["mapa_semantico"].values()))

    def test_zip_desconhecido_recusado(self):
        dst=io.BytesIO()
        with ZipFile(dst,"w") as z:
            z.writestr("malicioso.txt","teste")
        with self.assertRaises(ErroXlsxProgresso):
            run(dst.getvalue())

    def test_hash_codigo_parser_com_64_hex(self):
        v=run()
        self.assertEqual(len(v["parser_codigo_sha256"]),64)
        self.assertTrue(all(c in "0123456789abcdef" for c in v["parser_codigo_sha256"]))

    def test_calendario_1904_bloqueado_sem_antecipar_semana(self):
        original=workbook()
        out=io.BytesIO()
        with ZipFile(io.BytesIO(original)) as zin, ZipFile(out,"w",ZIP_DEFLATED) as zout:
            for obj in zin.infolist():
                raw=zin.read(obj.filename)
                if obj.filename=="xl/workbook.xml":
                    node=ET.fromstring(raw)
                    tag="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbookPr"
                    props=node.find(tag)
                    if props is None:
                        props=ET.Element(tag)
                        node.insert(0,props)
                    props.set("date1904","1")
                    raw=ET.tostring(node,encoding="utf-8",xml_declaration=True)
                zout.writestr(obj.filename,raw)
        with self.assertRaisesRegex(ErroXlsxProgresso,"1904"):
            run(out.getvalue())

    def test_url_fora_dominios_conab_recusada(self):
        with self.assertRaises(ErroXlsxProgresso):
            run(url="https://evil.example/relatorio.xlsx")


if __name__=="__main__":
    unittest.main()
