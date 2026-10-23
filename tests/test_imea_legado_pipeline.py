"""IMEA AgroLog -> NIVON: ensaio E2E com workbook XLSX inteiramente sintetico."""
import copy
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from nivon.imea_legado_pipeline import (
    MIME_XLSX, STAGING, ErroIntegracaoImea, preparar_lote,
    persistir_lote_local,
)
from nivon.imea_operacional_xlsx import parse_workbook


REGIOES = (
    "CENTRO-SUL", "MÉDIO-NORTE", "NORDESTE", "NOROESTE",
    "NORTE", "OESTE", "SUDESTE", "TOTAL MT",
)
REF = "2026-10-20T15:00:00Z"
ORIGEM = "https://drive.google.com/file/d/WORKBOOK_SINTETICO"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _serial(d=date(2026, 10, 19)):
    return (d - date(1899, 12, 30)).days


def _sheet(rows):
    text = [f'<worksheet xmlns="{NS}"><sheetData>']
    for i, row in enumerate(rows, 1):
        text.append(f'<row r="{i}">')
        for j, item in enumerate(row):
            col = chr(ord("A") + j)
            if item is None:
                continue
            if isinstance(item, (float, int)):
                text.append(f'<c r="{col}{i}"><v>{item}</v></c>')
            else:
                text.append(f'<c r="{col}{i}" t="inlineStr"><is><t>{escape(str(item))}</t></is></c>')
        text.append("</row>")
    text.append("</sheetData></worksheet>")
    return "".join(text).encode("utf-8")


def workbook_imea(*, preco=125.5, progresso=0.2, repeticao=False,
                  dtd=False, indicador_invalido=False):
    data = _serial()
    indicador = float("nan") if indicador_invalido else preco
    pair = [["DATA", "PRODUTO", "INFORMAÇÃO", "LOCAL", "UNIDADE", "DADO"],
            [data, "SOJA", "INDICADOR PUBLICADO", "MT", "R$/sc", indicador]]
    if repeticao:
        pair.append(list(pair[-1]))
    semanal = [["DATA", "PRODUTO", "INFORMAÇÃO", "LOCAL", "UNIDADE", "DADO"],
               [data, "MILHO", "INDICADOR SEMANAL", "MT", "R$/sc", 54.8]]
    frete = [["DATA", "PRODUTO", "TIPO_FRETE", "ORIGEM", "DESTINO", "FRETE", "UNIDADE"],
             [data, "SOJA", "REFERENCIA", "LUCAS DO RIO VERDE", "SANTOS", 250, "R$/T"]]
    cabecalho = ["DATA", "PRODUTO", "SAFRA", *REGIOES]
    linhas = [cabecalho, [data, "SOJA", "2026/27", *([progresso] * 8)]]
    abas = {
        "indicadores diarios": pair,
        "indicadores semanais": semanal,
        "frete": frete,
        "semeadura": linhas,
        "colheita": linhas,
    }
    workbook = f'<workbook xmlns="{NS}" xmlns:r="{RELS}"><sheets>'
    relationships = f'<Relationships xmlns="{PKG}">'
    out = io.BytesIO()
    with ZipFile(out, mode="w", compression=ZIP_DEFLATED) as z:
        for i, (name, rows) in enumerate(abas.items(), 1):
            workbook += f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
            relationships += (
                f'<Relationship Id="rId{i}" '
                f'Type="{RELS}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            )
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet(rows))
        workbook += "</sheets></workbook>"
        relationships += "</Relationships>"
        if dtd:
            workbook = '<!DOCTYPE workbook [<!ENTITY bomb "proibido">]>' + workbook
        z.writestr("xl/workbook.xml", workbook.encode("utf-8"))
        z.writestr("xl/_rels/workbook.xml.rels", relationships.encode("utf-8"))
    return out.getvalue()


class TestImeaLegadoPipeline(unittest.TestCase):
    def test_cinco_abas_pipeline_and_metadata(self):
        lote = preparar_lote(workbook_imea(), origem=ORIGEM, coletado_em=REF)
        self.assertEqual(lote["dataset_id"], STAGING)
        self.assertEqual(lote["tipo"], MIME_XLSX)
        self.assertEqual(lote["estado"], "QUARANTINED")
        self.assertEqual(len(lote["registros"]), 19)
        self.assertEqual(lote["contagem_abas"]["frete"], 1)
        self.assertEqual(lote["contagem_abas"]["semeadura"], 8)
        self.assertEqual(lote["contagem_abas"]["colheita"], 8)
        for registro in lote["registros"]:
            self.assertEqual(registro["referencia"], "2026-10-19")
            self.assertEqual(registro["competencia"], "2026-10")
            self.assertIsNone(registro["publicacao"])
            self.assertFalse(registro["campos"]["publicacao_verificada"])
        frete = [r for r in lote["registros"] if r["campos"]["planilha"] == "frete"][0]
        self.assertEqual(frete["natureza"], "INFORMADO")
        self.assertFalse(frete["campos"]["frete_negociado_comprovado"])
        self.assertIsNone(frete["campos"]["mapeamento_canonico_sugerido"])
        progressos = [r for r in lote["registros"] if r["campos"]["planilha"] == "semeadura"]
        self.assertTrue(all(r["natureza"] == "ESTIMADO" for r in progressos))
        self.assertTrue(all(r["campos"]["mapeamento_canonico_sugerido"] == "IMEA_MT_SAFRA"
                            for r in progressos))

    def test_e2e_sqlite_raw_revision_and_idempotency(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            args = {"banco": base / "imea.sqlite", "pasta_raw": base / "raw"}
            um = preparar_lote(workbook_imea(), origem=ORIGEM, coletado_em=REF)
            resultado = persistir_lote_local(um, **args)
            self.assertEqual(resultado["status"], "QUARENTENA_LOCAL")
            self.assertEqual(resultado["lote"]["novas_observacoes"], 19)
            dois = persistir_lote_local(um, **args)
            self.assertEqual(dois["lote"]["novas_observacoes"], 0)
            revisado = preparar_lote(workbook_imea(preco=126.5), origem=ORIGEM,
                                    coletado_em="2026-10-21T15:00:00Z")
            tres = persistir_lote_local(revisado, **args)
            self.assertEqual(tres["lote"]["novas_observacoes"], 1)
            with sqlite3.connect(args["banco"]) as con:
                snaps = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
                obs = con.execute("SELECT COUNT(*) FROM observacoes").fetchone()[0]
                estados = con.execute("SELECT DISTINCT estado FROM snapshots").fetchall()
                revisoes = con.execute("SELECT COUNT(DISTINCT valor) FROM observacoes "
                                       "WHERE campos_json LIKE '%INDICADOR PUBLICADO%'").fetchone()[0]
            self.assertEqual((snaps, obs, revisoes), (2, 20, 2))
            self.assertEqual(estados, [("QUARANTINED",)])
            self.assertEqual(len(list((base / "raw" / STAGING).glob("*.raw"))), 2)

    def test_real_requires_explicit_rights(self):
        lote = preparar_lote(workbook_imea(), origem=ORIGEM, coletado_em=REF)
        with tempfile.TemporaryDirectory() as folder:
            args = {"banco": Path(folder) / "db", "pasta_raw": Path(folder) / "raw"}
            with self.assertRaises(PermissionError):
                persistir_lote_local(lote, tipo="REAL_AUTORIZADO", **args)
            with self.assertRaises(PermissionError):
                persistir_lote_local(lote, tipo="REAL_AUTORIZADO",
                                     autorizacoes=frozenset({"COLETA"}),
                                     evidencia="permissao-pessoal-existente", **args)
            ret = persistir_lote_local(
                lote, tipo="REAL_AUTORIZADO",
                autorizacoes=frozenset({"COLETA", "ARMAZENAMENTO", "USO_INTERNO"}),
                evidencia="Autorização específica registrada e confirmada",
                **args,
            )
            self.assertFalse(ret["persistencia_google_cloud"])
            self.assertFalse(ret["publicacao_automatica"])

    def test_rejects_future_publication_and_bad_sources(self):
        with self.assertRaises(ErroIntegracaoImea):
            preparar_lote(workbook_imea(), origem=ORIGEM, coletado_em=REF,
                          publicado_em="2026-10-21")
        with self.assertRaises(ErroIntegracaoImea):
            preparar_lote(workbook_imea(), origem="https://127.0.0.1/imea",
                          coletado_em=REF)
        with self.assertRaises(ErroIntegracaoImea):
            preparar_lote(workbook_imea(), origem="http://drive.google.com/fake",
                          coletado_em=REF)
        with self.assertRaises(ErroIntegracaoImea):
            preparar_lote(workbook_imea(), origem=ORIGEM,
                          coletado_em="2026-10-20")

    def test_rejects_corruption_and_xml_entities(self):
        with self.assertRaises(ErroIntegracaoImea):
            preparar_lote(b"nao e xlsx", origem=ORIGEM, coletado_em=REF)
        with self.assertRaises(ErroIntegracaoImea):
            preparar_lote(workbook_imea(dtd=True), origem=ORIGEM, coletado_em=REF)

    def test_rejects_duplicate_header_malformed_value_and_progress(self):
        with self.assertRaises(ErroIntegracaoImea):
            preparar_lote(workbook_imea(repeticao=True), origem=ORIGEM, coletado_em=REF)
        with self.assertRaises(ErroIntegracaoImea):
            preparar_lote(workbook_imea(indicador_invalido=True), origem=ORIGEM, coletado_em=REF)
        with self.assertRaises(ErroIntegracaoImea):
            preparar_lote(workbook_imea(progresso=1.1), origem=ORIGEM, coletado_em=REF)

    def test_lote_not_promotable_to_normalized_via_entrypoint(self):
        lote = preparar_lote(workbook_imea(), origem=ORIGEM, coletado_em=REF)
        outro = dict(lote, estado="NORMALIZED")
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ErroIntegracaoImea):
                persistir_lote_local(outro, banco=Path(folder) / "db", pasta_raw=Path(folder) / "raw")

    def test_parser_legacy_all_sheets_equal(self):
        parsed = parse_workbook(workbook_imea())
        self.assertEqual(parsed["source_id"], "imea_operational_xlsx")
        self.assertEqual(parsed["qa"]["records"], 19)
        self.assertEqual(parsed["qa"]["natural_key_duplicates"], 0)
        self.assertEqual(set(parsed["qa"]["sheet_counts"]), {
            "indicadores diarios", "indicadores semanais", "frete", "semeadura", "colheita"
        })


if __name__ == "__main__":
    unittest.main()
