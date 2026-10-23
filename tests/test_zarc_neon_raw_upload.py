"""Testes de upload privado com duas URLS assinadas (reais NÃO usadas)."""
from __future__ import annotations

import csv
import gzip
import io
import tempfile
import unittest
from pathlib import Path

from nivon.zarc_staging import abrir_zarc_staging, importar_zarc_local
from nivon.zarc_raw_vault import guardar_raw_zarc
from nivon.zarc_stream_mt import COLUNAS
from nivon.zarc_neon_raw_upload import (
    HOST,BUCKET,ErroZarcRemoto,_url_aprovada,chave_objeto,enviar_raw_neon
)

CAT={"datasets":[{"id":"ZARC_JANELAS","source_id":"ZARC",
                  "enabled":False,"collection_authorized":False}]}

def dados():
    s=io.StringIO()
    w=csv.DictWriter(s,fieldnames=COLUNAS,delimiter=";",lineterminator="\n")
    w.writeheader()
    d={k:"" for k in COLUNAS}
    d.update({
        "Nome_cultura":"CULTURA_FICTICIA","SafraIni":"2026",
        "SafraFin":"2027","Cod_Cultura":"99","Cod_Ciclo":"20",
        "Cod_Solo":"2","geocodigo":"5105259","UF":"MT",
        "municipio":"FICTICIO","Cod_Clima":"7",
        "Cod_Outros_Manejos":"1","Portaria":"TESTE","Cod_Munic":"1",
    })
    w.writerow(d)
    return s.getvalue().encode("utf-8-sig")


def presign(sha,host=HOST,key=None,op="upload"):
    key=key or chave_objeto(sha)
    return ("https://"+host+"/"+BUCKET+"/"+key+
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=60&X-Amz-Signature="+
        "a"*64+"&X-Amz-SignedHeaders=host")


class Response:
    def __init__(self,body,status,url):
        self.buf=io.BytesIO(body)
        self.status=status
        self.url=url
    def read(self,n=-1):
        return self.buf.read(n)
    def geturl(self):
        return self.url
    def __enter__(self):
        return self
    def __exit__(self,*unused):
        self.buf.close()
        return False


class FakeOpener:
    def __init__(self,modify_get=None):
        self.calls=[]
        self.zipped=None
        self.modify_get=modify_get
    def open(self,req,timeout=0):
        method=req.get_method()
        self.calls.append(method)
        if method=="PUT":
            self.zipped=req.data.read()
            return Response(b"",200,req.full_url)
        if method=="GET":
            b=self.zipped if self.modify_get is None else self.modify_get(self.zipped)
            return Response(b,200,req.full_url)
        raise AssertionError("método não autorizado")


class TestZarcRemoteRaw(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root=Path(self.dir.name)/"raw"
        self.root.mkdir(mode=0o700)
        self.db=abrir_zarc_staging()
        self.addCleanup(self.db.close)
        self.b=dados()
        self.sha=importar_zarc_local(self.db,CAT,io.BytesIO(self.b),
             coletado_em="2026-10-22T12:00:00-04:00")["sha256"]
        guardar_raw_zarc(db=self.db,arquivo=io.BytesIO(self.b),
                          raiz=self.root)
        self.put=presign(self.sha)
        self.get=presign(self.sha,op="download")

    def test_transfere_e_rele_hash_csv_original(self):
        sender=FakeOpener()
        info=enviar_raw_neon(db=self.db,raiz_local=self.root,
            sha256=self.sha,put_url=self.put,get_url=self.get,
            executar=True,abridor=sender)
        self.assertEqual(sender.calls,["PUT","GET"])
        self.assertEqual(info["source_bytes"],len(self.b))
        self.assertEqual(info["bytes_recuperados_e_verificados"],len(self.b))
        self.assertEqual(gzip.decompress(sender.zipped),self.b)
        self.assertTrue(info["cloud_duravel_comprovado"])
        self.assertFalse(info["backup_independente"])
        self.assertFalse(info["publicavel"])
        self.assertFalse(info["inserido_no_banco_agricola"])
        self.assertNotIn("X-Amz-Signature",str(info))

    def test_sem_optin_automatico(self):
        with self.assertRaises(PermissionError):
            enviar_raw_neon(db=self.db,raiz_local=self.root,sha256=self.sha,
                            put_url=self.put,get_url=self.get)

    def test_outro_host_bucket_sha_http_ou_assinatura(self):
        cases=[
            self.put.replace("https://","http://"),
            self.put.replace(HOST,"evil.example"),
            self.put.replace(BUCKET,"bucket-publico"),
            self.put.replace(self.sha,"f"*64),
            self.put.split("?")[0],
            self.put+"&X-Amz-Signature=duplicado",
        ]
        for url in cases:
            with self.subTest(url=url.split("?")[0]),self.assertRaises(ErroZarcRemoto):
                _url_aprovada(url,self.sha)

    def test_corrompido_remoto_nao_faz_afirmacao_de_sucesso(self):
        sender=FakeOpener(modify_get=lambda data: data[:-4]+b"xxxx")
        with self.assertRaises(ErroZarcRemoto):
            enviar_raw_neon(db=self.db,raiz_local=self.root,sha256=self.sha,
                put_url=self.put,get_url=self.get,executar=True,abridor=sender)
        self.assertEqual(sender.calls,["PUT","GET"])

    def test_retorno_de_arquivo_diferente_falha(self):
        sender=FakeOpener(modify_get=lambda data: gzip.compress(b"OUTRO ARQUIVO"))
        with self.assertRaises(ErroZarcRemoto):
            enviar_raw_neon(db=self.db,raiz_local=self.root,sha256=self.sha,
                put_url=self.put,get_url=self.get,executar=True,abridor=sender)

    def test_sem_edicao_ledger_nao_faz_http(self):
        sender=FakeOpener()
        with self.assertRaises(Exception):
            enviar_raw_neon(db=abrir_zarc_staging(),raiz_local=self.root,
                sha256=self.sha,put_url=self.put,get_url=self.get,
                executar=True,abridor=sender)
        self.assertEqual(sender.calls,[])

if __name__=="__main__":
    unittest.main()
