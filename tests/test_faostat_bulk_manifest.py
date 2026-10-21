"""FAOSTAT manifest: contrato teste local, sem baixar ZIPs."""
import json
import unittest
from datetime import datetime,timezone
from nivon.faostat_bulk_manifest import (
 ErroFAOBulk,normalizar_manifest,consultar_manifest)

NOW=datetime(2026,10,21,20,tzinfo=timezone.utc)
URL="https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip"


def fixture():
    return {"Datasets":{"Dataset":[
        {"DatasetCode":"QCL","DatasetName":"Production: Crops and livestock products",
         "DateUpdate":"2025-12-31T00:00:00","CompressionFormat":"zip",
         "FileType":"csv","FileSize":"33127KB","FileRows":4209110,"FileLocation":URL},
        {"DatasetCode":"ZZ","DatasetName":"Other", "DateUpdate":"2026-01-01T00:00:00"}]}}


class Response:
    status=200
    headers={"Content-Type":"application/json"}
    def __init__(self,url,content):self.url,self.content=url,content
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.content[:n]


class Opener:
    def __init__(self,data):self.data,self.calls=data,[]
    def open(self,req,timeout):
        self.calls.append(req.full_url)
        return Response(req.full_url,json.dumps(self.data).encode())


class TestFAOBulk(unittest.TestCase):
    def test_subset_canonical_no_download(self):
        op=Opener(fixture())
        with self.assertRaises(PermissionError): consultar_manifest(abridor=op)
        self.assertFalse(op.calls)
        d=consultar_manifest(executar=True,abridor=op,instante=NOW)
        self.assertEqual(len(op.calls),1)
        self.assertEqual(d["total_dominios_manifest"],2)
        self.assertEqual(d["total_prioritarios"],1)
        self.assertEqual(d["dominios_prioritarios"][0]["total_linhas_informado"],4209110)
        self.assertFalse(d["arquivos_grandes_baixados"])
        self.assertEqual(d["coleta"],"2026-10-21T20:00:00+00:00")
        self.assertIsNone(d["publicacao_individual"])

    def test_malicious_url_source_blocked(self):
        for url in ("https://evil.invalid/a.zip","http://bulks-faostat.fao.org/production/a.zip",
                    "https://bulks-faostat.fao.org/../etc/passwd.zip"):
            with self.subTest(url=url):
                b=fixture();b["Datasets"]["Dataset"][0]["FileLocation"]=url
                with self.assertRaises(ErroFAOBulk):
                    normalizar_manifest(json.dumps(b).encode(),coletado_em="2026-10-21T20:00:00Z")

    def test_deny_dup_missing_qcl_and_bad_rows(self):
        b=fixture();b["Datasets"]["Dataset"][1]["DatasetCode"]="QCL"
        with self.assertRaises(ErroFAOBulk):
            normalizar_manifest(json.dumps(b).encode(),coletado_em="2026-10-21T20:00:00Z")
        b=fixture();b["Datasets"]["Dataset"][0]["FileRows"]=-1
        with self.assertRaises(ErroFAOBulk):
            normalizar_manifest(json.dumps(b).encode(),coletado_em="2026-10-21T20:00:00Z")
        b=fixture();b["Datasets"]["Dataset"]=b["Datasets"]["Dataset"][1:]
        with self.assertRaises(ErroFAOBulk):
            normalizar_manifest(json.dumps(b).encode(),coletado_em="2026-10-21T20:00:00Z")


if __name__=="__main__":
    unittest.main()
