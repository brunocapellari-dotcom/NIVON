"""Testes E2E reais (com OOXML sintético) do pipeline CONAB de 4 etapas.

Constroem workbook ZIP com abas e células, entregam os arquivos ao CLI em
disco e validam o dossiê. Não utilizam nenhum arquivo ou número real da CONAB.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase
from zipfile import ZipFile
from io import BytesIO

from nivon.conab_anexo_xlsx_levantamento import ErroDocumentoConab
from nivon.conab_celulas_xlsx import ler_amostra_celulas_conab
from nivon.conab_lote_offline import executar_lote_conab, ErroLoteConab
from nivon.conab_anexo_xlsx_levantamento import conferir_anexo_xlsx_levantamento
from test_conab_anexo_xlsx_levantamento import args as captura_args
from test_conab_ooxml_metadados import fixtures, DOC, TYPES, PKG, REL


def _zip(parts):
    f=BytesIO()
    with ZipFile(f,"w") as z:
        for name, content in parts.items():
            z.writestr(name,content)
    return f.getvalue()


def _workbook():
    parts=fixtures()
    parts["xl/sharedStrings.xml"]=(
        f'<sst xmlns="{DOC}" count="1" uniqueCount="1">'
        '<si><t>MT</t></si></sst>'
    ).encode()
    parts["xl/worksheets/sheet1.xml"]=(
        f'<worksheet xmlns="{DOC}"><sheetData>'
        '<row r="1">'
        '<c r="A1" t="inlineStr"><is><t>SOJA</t></is></c>'
        '<c r="B1" t="s"><v>0</v></c>'
        '</row>'
        '<row r="2">'
        '<c r="A2"><v>1234.5</v></c>'
        '<c r="B2" t="b"><v>1</v></c>'
        '</row>'
        '</sheetData></worksheet>'
    ).encode()
    parts["xl/worksheets/sheet2.xml"]=(
        f'<worksheet xmlns="{DOC}"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>MILHO</t></is></c></row>'
        '</sheetData></worksheet>'
    ).encode()
    return parts


def _input(raw=None):
    if raw is None:
        raw=_zip(_workbook())
    args=captura_args()
    args["xlsx_raw"]=raw
    args["sha256_xlsx_esperado"]=sha256(raw).hexdigest()
    vinculo=conferir_anexo_xlsx_levantamento(**args)
    return vinculo,raw


def _job(root: Path, ident="conab_2023_24_03", bad_sha=False):
    capture=captura_args()
    workbook=_zip(_workbook())
    files={
        "pagina_levantamento.html":capture["html_levantamento_raw"],
        "pagina_anexo.html":capture["html_anexo_raw"],
        "boletim.xlsx":workbook,
    }
    for name, content in files.items():
        (root/name).write_bytes(content)
    return {
        "job_id": ident, "safra":capture["safra"],
        "numero_levantamento":capture["numero_levantamento"],
        "pagina_levantamento_url":capture["pagina_levantamento_url"],
        "pagina_anexo_url":capture["pagina_anexo_url"],
        "arquivo_xlsx_url":capture["arquivo_xlsx_url"],
        "html_levantamento":"pagina_levantamento.html",
        "html_anexo":"pagina_anexo.html", "xlsx":"boletim.xlsx",
        "sha256_html_levantamento":sha256(files["pagina_levantamento.html"]).hexdigest(),
        "sha256_html_anexo":sha256(files["pagina_anexo.html"]).hexdigest(),
        "sha256_xlsx_esperado":("0"*64 if bad_sha else sha256(workbook).hexdigest()),
        "coletado_levantamento_em":capture["coletado_levantamento_em"],
        "coletado_anexo_em":capture["coletado_anexo_em"],
        "coletado_xlsx_em":capture["coletado_xlsx_em"],
    }


class TestLoteConabE2E(TestCase):
    def test_extrai_celulas_texto_numero_e_booleano(self):
        manifest,raw=_input()
        out=ler_amostra_celulas_conab(manifesto_vinculo=manifest,xlsx_raw=raw)
        self.assertEqual(out["abas_amostradas"],2)
        self.assertEqual(out["total_abas_documento"],2)
        cells=out["abas"][0]["amostra_celulas"]
        self.assertEqual([(x["referencia"],x["tipo"],x["valor"]) for x in cells],[
            ("A1","texto","SOJA"),
            ("B1","texto_compartilhado","MT"),
            ("A2","numero","1234.5"),
            ("B2","booleano","1"),
        ])
        self.assertFalse(out["tabela_agricola_normalizada"])
        self.assertFalse(out["disponibilidade_asof_comprovada"])
        self.assertFalse(out["habilita_backtest"])

    def test_lote_pipeline_completo_persistencia_dossie(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"raw"
            raw.mkdir()
            job=_job(raw)
            manifest={"schema_version":"1.0","jobs":[job]}
            output=executar_lote_conab(manifesto=manifest,base_dir=raw)
            self.assertEqual((output["total"],output["inspecionados"],output["rejeitados"]),
                             (1,1,0))
            result=output["resultados"][0]
            self.assertEqual(result["resultado"],"INSPECAO_OFFLINE_CONCLUIDA")
            self.assertEqual(result["vinculo"]["zip_entradas"],7)
            self.assertTrue(result["amostra_layout"]["celulas_xlsx_lidas"])
            self.assertEqual(result["amostra_layout"]["abas"][0]["amostra_celulas"][1]["valor"],"MT")
            self.assertFalse(result["habilita_backtest"])
            self.assertFalse(output["captura_real_verificada_externamente"])

    def test_cli_um_comando_gera_relatorio_sem_coleta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"raw"
            raw.mkdir()
            manifest_file=root/"jobs.json"
            output_file=root/"resultado.json"
            manifest_file.write_text(json.dumps({
                "schema_version":"1.0","jobs":[_job(raw)]
            }),encoding="utf-8")
            project=Path(__file__).resolve().parents[1]
            env=os.environ.copy()
            env["PYTHONPATH"]=str(project/"src") + os.pathsep + env.get("PYTHONPATH","")
            cmd=[sys.executable,"-m","nivon.conab_lote_offline",
                 "--manifest",str(manifest_file),"--base-dir",str(raw),
                 "--out",str(output_file)]
            run=subprocess.run(cmd,cwd=project,env=env,capture_output=True,
                               text=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertIn("INSPECIONADOS=1 REJEITADOS=0",run.stdout)
            dossier=json.loads(output_file.read_text(encoding="utf-8"))
            self.assertEqual(dossier["inspecionados"],1)
            # Não sobrescrever artefato anterior, mesmo que segunda chamada seja igual.
            repeat=subprocess.run(cmd,cwd=project,env=env,capture_output=True,
                                  text=True,timeout=20)
            self.assertEqual(repeat.returncode,3)
            self.assertEqual(json.loads(output_file.read_text())["inspecionados"],1)

    def test_lote_continua_apos_sha_errado_sem_abrir_xlsx(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw=Path(tmp)
            bad=_job(raw,bad_sha=True)
            result=executar_lote_conab(
                manifesto={"schema_version":"1.0","jobs":[bad]},base_dir=raw)
            self.assertEqual(result["rejeitados"],1)
            self.assertIsNone(result["resultados"][0]["amostra_layout"])
            self.assertFalse(result["habilita_publicacao"])

    def test_lote_nao_aceita_manifesto_com_job_duplicado(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            job=_job(root)
            with self.assertRaisesRegex(ErroLoteConab,"duplicada"):
                executar_lote_conab(manifesto={
                    "schema_version":"1.0",
                    "jobs":[job,dict(job,job_id="outro_job")]},base_dir=root)

    def test_lote_rejeita_symlink_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/"raw"
            base.mkdir()
            job=_job(base)
            src=base/"boletim.xlsx"
            external=Path(tmp)/"fora.xlsx"
            src.rename(external)
            src.symlink_to(external)
            result=executar_lote_conab(manifesto={
                "schema_version":"1.0","jobs":[job]},base_dir=base)
            self.assertEqual(result["rejeitados"],1)
            self.assertIn("simbólico",result["resultados"][0]["motivo"])

    def test_lote_rejeita_traversal_de_caminho(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            job=_job(root)
            job["xlsx"]="../fora.xlsx"
            result=executar_lote_conab(manifesto={
                "schema_version":"1.0","jobs":[job]},base_dir=root)
            self.assertEqual(result["rejeitados"],1)
            self.assertIn("traversal",result["resultados"][0]["motivo"])

    def test_rejeita_formula_antes_de_relatorio(self):
        d=_workbook()
        d["xl/worksheets/sheet1.xml"]=d["xl/worksheets/sheet1.xml"].replace(
            b"<v>1234.5</v>",b"<f>SUM(1,2)</f><v>3</v>"
        )
        manifest,raw=_input(_zip(d))
        with self.assertRaisesRegex(ErroDocumentoConab,"fórmula"):
            ler_amostra_celulas_conab(manifesto_vinculo=manifest,xlsx_raw=raw)

    def test_rejeita_shared_strings_invalida(self):
        d=_workbook()
        d["xl/worksheets/sheet1.xml"]=d["xl/worksheets/sheet1.xml"].replace(
            b"<v>0</v>",b"<v>99</v>"
        )
        manifest,raw=_input(_zip(d))
        with self.assertRaisesRegex(ErroDocumentoConab,"sharedStrings"):
            ler_amostra_celulas_conab(manifesto_vinculo=manifest,xlsx_raw=raw)

    def test_rejeita_celula_fora_da_janela(self):
        d=_workbook()
        d["xl/worksheets/sheet1.xml"]=d["xl/worksheets/sheet1.xml"].replace(
            b'r="A2"',b'r="XFE2"'
        )
        manifest,raw=_input(_zip(d))
        with self.assertRaisesRegex(ErroDocumentoConab,"fora da janela"):
            ler_amostra_celulas_conab(manifesto_vinculo=manifest,xlsx_raw=raw)

    def test_rejeita_celula_repetida(self):
        d=_workbook()
        body=d["xl/worksheets/sheet1.xml"]
        d["xl/worksheets/sheet1.xml"]=body.replace(
            b"</row>",b'<c r="A1"><v>123</v></c></row>',1
        )
        manifest,raw=_input(_zip(d))
        with self.assertRaisesRegex(ErroDocumentoConab,"repetida"):
            ler_amostra_celulas_conab(manifesto_vinculo=manifest,xlsx_raw=raw)

    def test_rejeita_numero_nao_finito(self):
        d=_workbook()
        d["xl/worksheets/sheet1.xml"]=d["xl/worksheets/sheet1.xml"].replace(
            b"<v>1234.5</v>",b"<v>NaN</v>"
        )
        manifest,raw=_input(_zip(d))
        with self.assertRaisesRegex(ErroDocumentoConab,"número"):
            ler_amostra_celulas_conab(manifesto_vinculo=manifest,xlsx_raw=raw)

    def test_rejeita_limites_sem_booleano(self):
        m,r=_input()
        with self.assertRaisesRegex(ErroDocumentoConab,"limites"):
            ler_amostra_celulas_conab(
                manifesto_vinculo=m,xlsx_raw=r,max_abas=True
            )


if __name__=="__main__":
    import unittest
    unittest.main()
