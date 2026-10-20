import unittest
from io import BytesIO
from unittest.mock import patch
from scripts.inspecionar_mdic_csv_headers import conferir,main,DATASETS

class Resp:
    status=206
    headers={"Content-Type":"text/plain"}
    def __init__(self,url,payload):
        self.url=url;self.data=BytesIO(payload)
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.data.read(n)
class Opener:
    def open(self,request,timeout):
        for url,header in DATASETS.values():
            if request.full_url==url:
                return Resp(url,(";".join(header)+"\n2026;DADO_PRIVADO\n").encode())
        raise AssertionError("URL errada")
class TestMDICHeaders(unittest.TestCase):
    def test_all_four_headers_verified_without_lines(self):
        x=conferir(abridor=Opener())
        self.assertEqual(len(x),4)
        self.assertTrue(all(v["estado"]=="HEADER_IGUAL" for v in x))
        self.assertNotIn("DADO_PRIVADO",str(x))
    def test_opt_in_required(self):
        with patch("scripts.inspecionar_mdic_csv_headers.build_opener",
                   side_effect=AssertionError("rede nao autorizada")):
            self.assertEqual(main([]),2)
