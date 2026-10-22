"""Inspeção real de metadados OOXML sobre ZIPs SINTÉTICOS, sem RAW CONAB."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from unittest import TestCase

from nivon.conab_anexo_xlsx_levantamento import (
    conferir_anexo_xlsx_levantamento, ErroDocumentoConab,
)
from nivon.conab_ooxml_metadados import inspecionar_abas_ooxml_conab
from test_conab_anexo_xlsx_levantamento import args as captura_args

TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WBCT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"


def fixtures():
    return {
        "[Content_Types].xml": (
            f'<Types xmlns="{TYPES}"><Override PartName="/xl/workbook.xml" '
            f'ContentType="{WBCT}"/></Types>'
        ).encode(),
        "_rels/.rels": (
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
            f'Type="{REL}/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        ).encode(),
        "xl/workbook.xml": (
            f'<workbook xmlns="{DOC}" xmlns:r="{REL}"><sheets>'
            '<sheet name="SOJA" sheetId="1" r:id="rId1"/>'
            '<sheet name="MILHO" sheetId="2" r:id="rId2" state="hidden"/>'
            '</sheets></workbook>'
        ).encode(),
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
            f'Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{REL}/worksheet" '
            'Target="/xl/worksheets/sheet2.xml"/></Relationships>'
        ).encode(),
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{DOC}"/>'.encode(),
        "xl/worksheets/sheet2.xml": f'<worksheet xmlns="{DOC}"/>'.encode(),
    }


def zipped(entries):
    f = BytesIO()
    with ZipFile(f, "w", ZIP_DEFLATED) as out:
        for name, raw in entries.items():
            out.writestr(name, raw)
    return f.getvalue()


def run(entries=None, raw=None, manifest_changes=None):
    data = zipped(fixtures() if entries is None else entries) if raw is None else raw
    args = captura_args()
    args["xlsx_raw"] = data
    args["sha256_xlsx_esperado"] = sha256(data).hexdigest()
    manifest = conferir_anexo_xlsx_levantamento(**args)
    if manifest_changes:
        manifest.update(manifest_changes)
    return inspecionar_abas_ooxml_conab(manifesto_vinculo=manifest, xlsx_raw=data)


class TestMetadadosOOXML(TestCase):
    def test_duas_abas_e_estado_sem_celulas(self):
        result = run()
        self.assertEqual(result["quantidade_abas"], 2)
        self.assertEqual([r["nome"] for r in result["abas"]], ["SOJA","MILHO"])
        self.assertEqual(result["abas"][1]["estado"], "hidden")
        self.assertEqual(result["abas"][0]["parte_xml"], "xl/worksheets/sheet1.xml")
        self.assertFalse(result["celulas_xlsx_lidas"])
        self.assertFalse(result["disponibilidade_asof_comprovada"])
        self.assertFalse(result["habilita_publicacao"])

    def test_manifesto_adulterado_ou_hash_trocado_reprova(self):
        raw=zipped(fixtures())
        args=captura_args()
        args["xlsx_raw"]=raw
        args["sha256_xlsx_esperado"]=sha256(raw).hexdigest()
        base=conferir_anexo_xlsx_levantamento(**args)
        base["arquivo_raw_sha256"]="f"*64
        with self.assertRaisesRegex(ErroDocumentoConab,"XLSX não corresponde"):
            inspecionar_abas_ooxml_conab(manifesto_vinculo=base,xlsx_raw=raw)

    def test_gates_manipulados_reprova(self):
        for key in ("habilita_treino","habilita_backtest","habilita_publicacao",
                    "disponibilidade_asof_comprovada","celulas_xlsx_lidas"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ErroDocumentoConab,"gate"):
                    run(manifest_changes={key:True})

    def test_sem_relationships_do_workbook(self):
        d=fixtures()
        del d["xl/_rels/workbook.xml.rels"]
        with self.assertRaisesRegex(ErroDocumentoConab,"workbook sem mapa"):
            run(d)

    def test_root_rel_nao_aponta_workbook(self):
        d=fixtures()
        d["_rels/.rels"]=d["_rels/.rels"].replace(
            b"xl/workbook.xml",b"xl/unknown.xml"
        )
        with self.assertRaisesRegex(ErroDocumentoConab,"workbook principal"):
            run(d)

    def test_destino_de_aba_inexistente(self):
        d=fixtures()
        d["xl/_rels/workbook.xml.rels"]=d[
            "xl/_rels/workbook.xml.rels"
        ].replace(b"worksheets/sheet1.xml",b"worksheets/missing.xml")
        with self.assertRaisesRegex(ErroDocumentoConab,"worksheet"):
            run(d)

    def test_aba_relacionada_a_tipo_errado(self):
        d=fixtures()
        d["xl/_rels/workbook.xml.rels"]=d[
            "xl/_rels/workbook.xml.rels"
        ].replace(b"/worksheet",b"/styles")
        with self.assertRaisesRegex(ErroDocumentoConab,"worksheet interno"):
            run(d)

    def test_relationship_externo_bloqueado_no_workbook(self):
        d=fixtures()
        d["xl/_rels/workbook.xml.rels"]=d[
            "xl/_rels/workbook.xml.rels"
        ].replace(b'Target="worksheets/sheet1.xml"',
                  b'Target="https://evil.invalid/file" TargetMode="External"')
        with self.assertRaisesRegex(ErroDocumentoConab,"externo"):
            run(d)

    def test_relationship_externo_bloqueado_em_subpasta(self):
        d=fixtures()
        d["xl/worksheets/_rels/sheet1.xml.rels"]=(
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
            f'Type="{REL}/hyperlink" Target="https://test.example" '
            'TargetMode="External"/></Relationships>'
        ).encode()
        with self.assertRaisesRegex(ErroDocumentoConab,"externo"):
            run(d)

    def test_relationship_traversal_bloqueado(self):
        d=fixtures()
        d["xl/_rels/workbook.xml.rels"]=d[
            "xl/_rels/workbook.xml.rels"
        ].replace(b"worksheets/sheet1.xml",b"../../etc/passwd")
        with self.assertRaisesRegex(ErroDocumentoConab,"sair do pacote"):
            run(d)

    def test_aba_duplicada_ignorando_maiusculas(self):
        d=fixtures()
        d["xl/workbook.xml"]=d["xl/workbook.xml"].replace(
            b'name="MILHO"',b'name="soja"'
        )
        with self.assertRaisesRegex(ErroDocumentoConab,"identidade"):
            run(d)

    def test_sheet_id_duplicado(self):
        d=fixtures()
        d["xl/workbook.xml"]=d["xl/workbook.xml"].replace(
            b'sheetId="2"',b'sheetId="1"'
        )
        with self.assertRaisesRegex(ErroDocumentoConab,"identidade"):
            run(d)

    def test_sheet_sem_rid(self):
        d=fixtures()
        d["xl/workbook.xml"]=d["xl/workbook.xml"].replace(
            b'r:id="rId2"',b'r:id="rIdExtra"'
        )
        with self.assertRaisesRegex(ErroDocumentoConab,"identidade"):
            run(d)

    def test_workbook_tipo_macro_rejeitado(self):
        d=fixtures()
        d["[Content_Types].xml"]=d["[Content_Types].xml"].replace(
            WBCT.encode(),b"application/vnd.ms-excel.sheet.macroEnabled.main+xml"
        )
        with self.assertRaisesRegex(ErroDocumentoConab,"content type"):
            run(d)

    def test_dtd_e_entidade_rejeitada(self):
        d=fixtures()
        d["xl/workbook.xml"]=(
            b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            +d["xl/workbook.xml"]
        )
        with self.assertRaisesRegex(ErroDocumentoConab,"DTD"):
            run(d)

    def test_workbook_xml_invalido(self):
        d=fixtures()
        d["xl/workbook.xml"]=b"<broken"
        with self.assertRaisesRegex(ErroDocumentoConab,"malformado"):
            run(d)

    def test_arquivo_nao_prova_numero_de_producao(self):
        value=run()
        for key in ("dados_agricolas_extraidos", "edicao_historica_autenticada",
                    "habilita_backtest", "habilita_treino","habilita_publicacao",
                    "integridade_xml_planilhas_validada"):
            self.assertIs(value[key],False)

    def test_manifesto_nao_estruturado_rejeitado(self):
        with self.assertRaises(ErroDocumentoConab):
            inspecionar_abas_ooxml_conab(manifesto_vinculo={},
                                         xlsx_raw=zipped(fixtures()))


if __name__=="__main__":
    import unittest
    unittest.main()
