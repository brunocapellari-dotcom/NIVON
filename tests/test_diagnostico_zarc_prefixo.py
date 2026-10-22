"""Regressão offline da amostra limitada de diagnóstico semântico ZARC."""
import csv
import io
import unittest
from nivon.zarc_stream_mt import COLUNAS, URL
from nivon.diagnostico_zarc_prefixo import examinar_prefixo, consultar_prefixo, ErroZarcAmostra

def payload(uf="MT",year="2026",portaria="Portaria 3",ibge="5105259"):
    d={k:"A" for k in COLUNAS}
    d.update({"UF":uf,"SafraIni":year,"SafraFin":"2027",
              "Portaria":portaria,"Nome_cultura":"Soja","geocodigo":ibge})
    out=io.StringIO()
    w=csv.DictWriter(out,fieldnames=COLUNAS,delimiter=";",lineterminator="\n")
    w.writeheader()
    w.writerow(d)
    return out.getvalue().encode("utf-8")

class Resp:
    status=200
    def __init__(self,blob,url=URL,mime="text/csv"):
        self.blob,self.url=blob,url
        self.headers={"Content-Type":mime}
        self.reads=[]
    def geturl(self):return self.url
    def read(self,n):self.reads.append(n);return self.blob[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False

class Open:
    def __init__(self,res):self.res=res;self.calls=0
    def open(self,req,timeout=35):
        self.calls+=1
        assert req.get_header("Range")=="bytes=0-4095"
        return self.res

class TestZarcPrefixo(unittest.TestCase):
    def test_sem_rede_default(self):
        with self.assertRaises(PermissionError):consultar_prefixo()
    def test_linhas_mt_validadas(self):
        b=payload()
        r=examinar_prefixo(b)
        self.assertEqual(r["linhas_mt_na_amostra"],1)
        self.assertEqual(r["linhas_completas_amostra"],1)
        self.assertEqual(r["regras_que_teriam_bloqueado"],{})
        self.assertFalse(r["persistido"])
    def test_contagem_de_regras(self):
        b=payload(year="2025",portaria="",ibge="invalid")
        r=examinar_prefixo(b)
        self.assertEqual(r["regras_que_teriam_bloqueado"]["GEOCODIGO_MT_NAO_IBGE7"],1)
        self.assertEqual(r["regras_que_teriam_bloqueado"]["SAFRA_MT_DIVERGENTE"],1)
        self.assertEqual(r["regras_que_teriam_bloqueado"]["PORTARIA_MT_AUSENTE_OU_LONGA"],1)
    def test_descarta_ultima_linha_truncada(self):
        r=examinar_prefixo(payload()+b"MT;2026;123")
        self.assertEqual(r["linhas_completas_amostra"],1)
    def test_execucao_opt_in_uma_requisicao(self):
        resp=Resp(payload())
        c=Open(resp)
        r=consultar_prefixo(executar=True,abridor=c,limite=4096)
        self.assertEqual(c.calls,1)
        self.assertEqual(resp.reads,[4096])
        self.assertEqual(r["http_status"],200)
        self.assertFalse(r["arquivo_integral_lido"])
    def test_rejeita_html_host_e_sem_newline(self):
        for r in (Resp(b"<html></html>",mime="text/html"),Resp(payload(),url="https://other.example/")):
            with self.assertRaises(ErroZarcAmostra):
                consultar_prefixo(executar=True,abridor=Open(r),limite=4096)
        with self.assertRaises(ErroZarcAmostra):examinar_prefixo(b"no-newline")
    def test_recusa_parametro_volume(self):
        for lim in (0, True,"4096",9*1024*1024):
            with self.assertRaises(ErroZarcAmostra):
                consultar_prefixo(executar=True,limite=lim)

if __name__=="__main__":
    unittest.main()
