"""Teste E2E coletor pontual CONAB -> arquivo RAW -> worker -> SQLite.

Transporte inteiramente simulado: NÃO é download nem homologação oficial.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
from unittest import TestCase, mock

from nivon.conab_coleta_pontual import (
    coletar_uma_edicao, ErroColetaPontualConab, _conferir_resposta,
)
from nivon.conab_lote_isolado import executar_worker_conab
from nivon.conab_anexo_xlsx_levantamento import ANEXO
from test_conab_lote_e2e import _zip, _workbook
from test_conab_anexo_xlsx_levantamento import ROOT

VIEW=ROOT+"/"+ANEXO+"/view"
RAW=VIEW.removesuffix("/view")
STAMP="2026-10-23T10:00:00-04:00"


def catalogo(path):
    entry={
        "fonte_id":"CONAB","safra":"2023/24","numero_levantamento":3,
        "pagina_url":ROOT,
        "publicado_portal_em":"2023-12-07T09:00:00-03:00",
        "atualizado_portal_em":"2025-01-24T12:45:00-03:00",
        "inspecionado_dia":"2026-10-23",
    }
    path.write_text(json.dumps([entry]),encoding="utf-8")
    return entry


def respostas():
    html=f'<html><a href="{VIEW}">Tabela CONAB</a></html>'.encode()
    annex=b'<html><h1>Tabela de dados - planilha</h1></html>'
    binary=_zip(_workbook())
    return {
        ROOT:{"bytes":html,"content_type":"text/html","final_url":ROOT},
        VIEW:{"bytes":annex,"content_type":"text/html; charset=utf-8","final_url":VIEW},
        RAW:{"bytes":binary,
             "content_type":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "final_url":RAW+"/@@download/file"},
    }


def simulate(mapping, seen):
    def pull(url, size):
        seen.append(url)
        d=deepcopy(mapping[url])
        d.update({"coletado_em":STAMP,"etag_http":'"fake"',
                  "last_modified_http":None,"status_http":200})
        return d
    return pull


class TestColetaPontualE2E(TestCase):
    def test_tres_raws_manifesto_e_worker_de_uma_edicao(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            cat=dest/"catalogo.json"
            catalogo(cat)
            seen=[]
            with mock.patch("nivon.conab_coleta_pontual._baixar",
                            side_effect=simulate(respostas(),seen)):
                out=coletar_uma_edicao(
                    safra="2023/24",numero=3,output_root=dest,catalogo=cat,
                )
            self.assertEqual(seen,[ROOT,VIEW,RAW])
            self.assertEqual(out["documentos"],3)
            self.assertFalse(out["disponibilidade_asof_comprovada"])
            self.assertTrue(Path(out["manifesto"]).is_file())
            folder=Path(out["diretorio"])
            job=json.loads((folder/"jobs.json").read_text())["jobs"][0]
            capture=json.loads((folder/"captura_http.json").read_text())
            self.assertEqual(
                job["sha256_xlsx_esperado"],
                sha256((folder/"tabela.xlsx").read_bytes()).hexdigest(),
            )
            self.assertTrue(capture["http"]["xlsx"]["final_url"].endswith("/@@download/file"))
            self.assertFalse(capture["publicacao_historica_provada"])
            dbfile=dest/"staging.sqlite"
            result=executar_worker_conab(
                manifesto=out["manifesto"],base_dir=out["diretorio_raw"],
                saida=str(dest/"dossie.json"),sqlite=str(dbfile),timeout_s=25,
            )
            self.assertEqual(result["exit_code"],0,result["stderr"])
            with sqlite3.connect(dbfile) as db:
                records=db.execute(
                    "SELECT arquivo_sha256,classe_status FROM nivon_conab_staging_documentos"
                ).fetchall()
            self.assertEqual(records,[(job["sha256_xlsx_esperado"],"OFFLINE_SEM_VINTAGE")])
            dossier=json.loads((dest/"dossie.json").read_text())
            self.assertEqual(dossier["inspecionados"],1)
            self.assertFalse(dossier["habilita_backtest"])

    def test_coletor_recusa_segunda_execucao_mesma_edicao(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            cat=dest/"cat.json"
            catalogo(cat)
            with mock.patch("nivon.conab_coleta_pontual._baixar",
                            side_effect=simulate(respostas(),[])):
                a=coletar_uma_edicao(safra="2023/24",numero=3,
                                     output_root=dest,catalogo=cat)
                with self.assertRaisesRegex(ErroColetaPontualConab,"já existe"):
                    coletar_uma_edicao(safra="2023/24",numero=3,
                                       output_root=dest,catalogo=cat)
            self.assertEqual(len(list(Path(a["diretorio"]).iterdir())),5)

    def test_coleta_incompleta_nao_deixa_dir_parcial(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            cat=dest/"cat.json"
            catalogo(cat)
            responses=respostas()
            responses[RAW]["bytes"]=b"<html>não é XLSX</html>"
            with mock.patch("nivon.conab_coleta_pontual._baixar",
                            side_effect=simulate(responses,[])):
                with self.assertRaises(ErroColetaPontualConab):
                    coletar_uma_edicao(safra="2023/24",numero=3,
                                       output_root=dest,catalogo=cat)
            self.assertFalse((dest/"conab_2023_24_levantamento_03").exists())
            self.assertEqual(list(dest.glob(".conab_tmp_*")),[])

    def test_redirecionamento_para_domino_alheio_bloqueia(self):
        fake={
            "bytes":b'PK\x03\x04'+b"0"*100,
            "content_type":"application/octet-stream",
            "final_url":"https://www.gov.br.evil.example/data",
            "status_http":200,"coletado_em":STAMP,
        }
        with self.assertRaises(ValueError):
            _conferir_resposta(fake,tipo="xlsx",url=RAW)

    def test_rejeita_captura_url_de_outra_edicao(self):
        res=respostas()
        res[RAW]["final_url"]=ROOT.replace("2023-24","2024-25")+"/data"
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            cat=dest/"cat.json"
            catalogo(cat)
            with mock.patch("nivon.conab_coleta_pontual._baixar",
                            side_effect=simulate(res,[])):
                with self.assertRaises(ErroColetaPontualConab):
                    coletar_uma_edicao(safra="2023/24",numero=3,
                                       output_root=dest,catalogo=cat)

    def test_catalogo_nao_cadastrado_nao_faz_requisicoes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            cat=dest/"cat.json"
            catalogo(cat)
            with mock.patch("nivon.conab_coleta_pontual._baixar") as request:
                with self.assertRaisesRegex(ErroColetaPontualConab,"não consta"):
                    coletar_uma_edicao(safra="2025/26",numero=6,
                                       output_root=dest,catalogo=cat)
                request.assert_not_called()

    def test_falso_html_de_levantamento_nao_liga_anexo(self):
        res=respostas()
        res[ROOT]["bytes"]=b"<html><a href='https://evil.invalid'>falso</a></html>"
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            cat=dest/"cat.json"
            catalogo(cat)
            with mock.patch("nivon.conab_coleta_pontual._baixar",
                            side_effect=simulate(res,[])):
                with self.assertRaisesRegex(ValueError,"anexo não encontrado"):
                    coletar_uma_edicao(safra="2023/24",numero=3,
                                       output_root=dest,catalogo=cat)
            self.assertEqual(list(dest.glob("conab_*")),[])


if __name__=="__main__":
    import unittest
    unittest.main()
