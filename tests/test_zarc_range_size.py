"""Provas offline do diagnóstico GET Range de um byte."""
import unittest
from nivon.zarc_range_size import consultar_tamanho, interpretar_resposta, ErroZarcTamanho
from nivon.zarc_stream_mt import URL, MAX_DOWNLOAD

class Response:
    def __init__(self,status=206,cr="bytes 0-0/170000001",url=URL,
                 mime="text/csv", cl=None):
        self.status=status
        self.url=url
        self.headers={"Content-Type":mime}
        if cr is not None:self.headers["Content-Range"]=cr
        if cl is not None:self.headers["Content-Length"]=cl
        self.lidos=[]
    def read(self,n):
        self.lidos.append(n)
        return b"N"
    def geturl(self):return self.url
    def __enter__(self):return self
    def __exit__(self,*x):return False

class Opener:
    def __init__(self,r):self.r=r;self.calls=0
    def open(self,req,timeout=20):
        self.calls+=1
        assert req.get_header("Range")=="bytes=0-0"
        return self.r

class TestZarcRange(unittest.TestCase):
    def test_off(self):
        with self.assertRaises(PermissionError):consultar_tamanho()
    def test_206_prova_tamanho_versus_teto_atual(self):
        resp=Response()
        cli=Opener(resp)
        out=consultar_tamanho(executar=True,abridor=cli)
        self.assertEqual(out["total_bytes_comprovado"],170000001)
        self.assertEqual(out["maior_que_limite_160mb"], 170000001 > MAX_DOWNLOAD)
        self.assertEqual(cli.calls,1)
        self.assertEqual(resp.lidos,[1])
        self.assertFalse(out["arquivo_integral_baixado"])
    def test_200_range_ignorado_usa_content_length(self):
        out=interpretar_resposta(url=URL,status=200,mime="text/csv",
                      content_range=None,content_length="2500",primeiro_byte=b"N")
        self.assertFalse(out["http_range_atendido"])
        self.assertEqual(out["total_bytes_comprovado"],2500)
    def test_sem_tamanho_nunca_inferir(self):
        out=interpretar_resposta(url=URL,status=200,mime="text/csv",
                      content_range=None,content_length=None,primeiro_byte=b"N")
        self.assertIsNone(out["total_bytes_comprovado"])
        self.assertIsNone(out["maior_que_limite_160mb"])
    def test_rejeitar_range_status_host_mime(self):
        bad=[
            (URL,206,"text/csv","bytes 100-100/170000000",None,b"N"),
            ("https://x.test/data",206,"text/csv","bytes 0-0/100",None,b"N"),
            (URL,200,"text/html",None,"400",b"N"),
            (URL,302,"text/csv",None,"400",b"N"),
            (URL,206,"text/csv","bytes 0-0/0",None,b"N"),
            (URL,206,"text/csv","bytes 0-0/100",None,b""),
        ]
        for x in bad:
            with self.subTest(x=x),self.assertRaises(ErroZarcTamanho):
                interpretar_resposta(url=x[0],status=x[1],mime=x[2],
                    content_range=x[3],content_length=x[4],primeiro_byte=x[5])

if __name__=="__main__":
    unittest.main()
