"""Testes de aquisição fixada e transação LAB; nunca fazem rede."""
import base64
import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

from nivon.lote_conab_integracao import (
    GITHUB_COMMIT,GITHUB_HOST,ErroLoteConab,_baixar_arquivo,
    obter_referencias_terceiro,executar_lote_laboratorio,main,
)
from nivon.auditoria_vintages_conab import auditar_vintages_conab

ROOT=Path(__file__).resolve().parents[1]
CAT=ROOT/"config"/"conab_referencias_multivintage_20261021.json"
FIXTURE=ROOT/"tests"/"fixtures"/"conab_progresso_agrobr_20260207.xlsx.b64"


class Reply:
    def __init__(self,url,body,status=200):
        self.status=status
        self.url=url
        self.stream=io.BytesIO(body)
        self.headers={"Content-Length":str(len(body))}
    def geturl(self):return self.url
    def read(self,size):return self.stream.read(size)
    def __enter__(self):return self
    def __exit__(self,*a):self.stream.close()


class TestLoteIntegracaoConab(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.catalog=json.loads(CAT.read_text())
        self.body=base64.b64decode(FIXTURE.read_text().strip(),validate=True)
        self.ref={
            "id":"AGROBR_20260207",
            "arquivo":"agrobr_20260207.xlsx",
            "origem_repositorio":"tests/golden_data/conab_progresso/progresso_sample/response.xlsx",
            "git_blob_sha1":"05d50fb46c23186ec8cee23f1969746acec082e4",
            "sha256":hashlib.sha256(self.body).hexdigest(),
            "bytes":len(self.body),
            "competencia":"2026-02-07",
            "captura_declarada":"2026-02-24T09:59:00Z",
            "url_original_declarada":"https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture",
            "observacoes_esperadas":11,
            "culturas_esperadas":["Soja","Milho 2ª"],
        }
    def one_catalog(self):
        return {**self.catalog,"edicoes":[self.ref]}
    def valid_url(self):
        return f"https://{GITHUB_HOST}/bruno-portfolio/agrobr/{GITHUB_COMMIT}/{self.ref['origem_repositorio']}"

    def test_mock_download_sha_e_arquivo_real_de_terceiro(self):
        requests=[]
        def http(req,timeout):
            requests.append((req.full_url,timeout))
            return Reply(req.full_url,self.body)
        data=_baixar_arquivo(self.ref,transport=http)
        self.assertEqual(data,self.body)
        self.assertEqual(requests,[(self.valid_url(),15)])
        result=obter_referencias_terceiro(self.one_catalog(),self.root,transport=http)
        self.assertEqual(result["baixados"],1)
        self.assertEqual((self.root/self.ref["arquivo"]).read_bytes(),self.body)
        self.assertFalse(result["migracao_permitida"])
        audit=auditar_vintages_conab(self.one_catalog(),self.root)
        self.assertEqual(audit["edicoes_presentes_reprocessadas"],1)

    def test_download_sha_falso_bloqueia_sem_gravar(self):
        with self.assertRaisesRegex(ErroLoteConab,"divergem"):
            obter_referencias_terceiro(
                {**self.one_catalog(),"edicoes":[{**self.ref,"sha256":"0"*64}]},
                self.root,transport=lambda req,timeout:Reply(req.full_url,self.body))
        self.assertEqual(list(self.root.iterdir()),[])

    def test_nao_tenta_outro_host_ou_ref(self):
        ref={**self.ref,"origem_repositorio":"../privado.xlsx"}
        with self.assertRaises(ErroLoteConab):
            _baixar_arquivo(ref,transport=lambda req,timeout:Reply(req.full_url,self.body))

    def test_redirect_nao_e_aceito(self):
        with self.assertRaisesRegex(ErroLoteConab,"redirect"):
            _baixar_arquivo(self.ref,transport=lambda req,timeout:
                    Reply("https://evil.example/file",self.body))
    def test_http_403_nao_contorna_bloqueio(self):
        with self.assertRaisesRegex(ErroLoteConab,"inesperada"):
            _baixar_arquivo(self.ref,transport=lambda req,timeout:
                    Reply(req.full_url,self.body,status=403))

    def test_erro_dns_falha_sem_rede_alternativa(self):
        calls=[]
        def fail(req,timeout):
            calls.append(1)
            raise urllib.error.URLError("DNS")
        with self.assertRaises(ErroLoteConab):
            _baixar_arquivo(self.ref,transport=fail)
        self.assertEqual(calls,[1])

    def test_lote_exige_minimo_duas_vintages(self):
        (self.root/self.ref["arquivo"]).write_bytes(self.body)
        import sqlite3
        with sqlite3.connect(":memory:") as db:
            with self.assertRaisesRegex(ErroLoteConab,"mínimo duas"):
                executar_lote_laboratorio(self.one_catalog(),self.root,db)

    def test_cli_sem_argumento_download_ou_diretorio_nao_executa(self):
        from contextlib import redirect_stderr
        out=io.StringIO()
        with redirect_stderr(out),self.assertRaises(SystemExit) as exc:
            main(["--catalogo",str(CAT)])
        self.assertEqual(exc.exception.code,2)


if __name__=="__main__":
    unittest.main()
