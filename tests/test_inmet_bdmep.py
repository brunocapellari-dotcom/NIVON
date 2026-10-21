"""BDMEP: link privado e download controlado simulados sem tráfego HTTP."""
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from nivon.inmet_bdmep import (
    ErroBDMEP, _url_privada, link_privado_do_ambiente,
    conferir_zip_bdmep, receber_bdmep,
)

SECRET_URL="https://bdmep.inmet.gov.br/$2a$10$"+"A"*53+".zip"

def fixture_zip():
    buff=io.BytesIO()
    with zipfile.ZipFile(buff,"w",compression=zipfile.ZIP_DEFLATED) as f:
        f.writestr("dados/serie.csv","DATA;CHUVA\n2026-07-12;2\n")
    return buff.getvalue()

class FakeResult:
    status=200
    def __init__(self,data):self.data=io.BytesIO(data)
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,n):return self.data.read(n)

class FakeOpener:
    def __init__(self,data):self.data=data;self.req=None
    def open(self,request,timeout):
        self.req=request
        return FakeResult(self.data)

class TestBDMEPPrivado(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)

    def test_url_token_aceito_apenas_dominio_oficial(self):
        self.assertEqual(_url_privada(SECRET_URL),SECRET_URL)
        for candidate in ("http://bdmep.inmet.gov.br/a.zip",
                          "https://bdmep.inmet.gov.br.evil.net/a.zip",
                          "https://bdmep.inmet.gov.br/data.zip",
                          SECRET_URL+"?token=leak",
                          SECRET_URL.replace("https://","https://ana:senha@")):
            with self.assertRaises(ErroBDMEP):_url_privada(candidate)

    def test_link_somente_em_env_secreta(self):
        with patch.dict(os.environ,{"NIVON_INMET_BDMEP_URL":SECRET_URL}):
            self.assertEqual(link_privado_do_ambiente(),SECRET_URL)
        with patch.dict(os.environ,{"NIVON_INMET_BDMEP_URL":""}):
            with self.assertRaises(ErroBDMEP):link_privado_do_ambiente()

    def test_rede_desligada_padrao(self):
        with self.assertRaises(PermissionError):
            receber_bdmep(pasta_privada=self.folder,url=SECRET_URL)

    def test_receber_zip_valido_sem_imprimir_url_ou_token(self):
        mock=FakeOpener(fixture_zip())
        result=receber_bdmep(pasta_privada=self.folder,habilitar_rede=True,
                            url=SECRET_URL,transporte=mock)
        self.assertTrue(Path(result["caminho_privado"]).exists())
        self.assertEqual(result["inventario"]["csv"],1)
        self.assertFalse(result["conteudo_publicado"])
        self.assertNotIn("bdmep.inmet.gov.br",str(result))
        self.assertNotIn("$2a$",str(result))
        self.assertEqual(mock.req.full_url,SECRET_URL)
        self.assertEqual(len(result["sha256"]),64)

    def test_corrompido_nao_fica_em_disco(self):
        with self.assertRaises(ErroBDMEP):
            receber_bdmep(pasta_privada=self.folder,habilitar_rede=True,
                 url=SECRET_URL,transporte=FakeOpener(b"nao_e_zip"*400))
        self.assertFalse(list(self.folder.iterdir()))

    def test_zip_injetado_path_traversal(self):
        buff=io.BytesIO()
        with zipfile.ZipFile(buff,"w") as z:
            z.writestr("../segredo.csv",b"csv")
        with self.assertRaises(ErroBDMEP):
            receber_bdmep(pasta_privada=self.folder,habilitar_rede=True,
                          url=SECRET_URL,transporte=FakeOpener(buff.getvalue()))
        self.assertFalse(list(self.folder.iterdir()))

    def test_nao_sobrescrever_conteudo_identico(self):
        data=fixture_zip()
        receber_bdmep(pasta_privada=self.folder,habilitar_rede=True,
                      url=SECRET_URL,transporte=FakeOpener(data))
        with self.assertRaises(ErroBDMEP):
            receber_bdmep(pasta_privada=self.folder,habilitar_rede=True,
                          url=SECRET_URL,transporte=FakeOpener(data))

    def test_sem_csv_nao_homologa(self):
        arquivo=self.folder/"empty.zip"
        buff=io.BytesIO()
        with zipfile.ZipFile(buff,"w") as z:z.writestr("README.txt",b"teste")
        arquivo.write_bytes(buff.getvalue())
        with self.assertRaises(Exception):
            conferir_zip_bdmep(arquivo)

if __name__=="__main__":
    unittest.main()
