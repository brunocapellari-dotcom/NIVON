"""Regressao local API BCRA v4, com snapshots transacionais."""
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from nivon.coletor_bcra_v4 import plano_bcra,parse_bcra,coletar_bcra
from nivon.coletores_dados_reais import ErroColetor
from nivon.ingestao_fontes_reais import exportar_jsonl

T=datetime(2026,10,22,tzinfo=timezone.utc)
DOC={"status":0,"metadata":{"resultset":{"count":2,"limit":250,"offset":0}},
     "results":[{"idVariable":1,"detalle":[{"fecha":"2026-10-01","valor":49300.0},
         {"fecha":"2026-10-02","valor":49355.0}]}]}

class Resp:
    status=200
    headers={"Content-Type":"text/plain"}
    def __init__(self,url,body):
        self.url=url
        self.body=body
    def geturl(self):
        return self.url
    def read(self,size):
        return self.body[:size]
    def __enter__(self):
        return self
    def __exit__(self,*a):
        return False

class Fake:
    def __init__(self,url,body):
        self.url=url
        self.body=body
    def open(self,req,timeout=30):
        if req.full_url!=self.url:
            raise AssertionError("unexpected URL")
        return Resp(self.url,self.body)

class BcraTest(unittest.TestCase):
    def test_plano_preciso_e_limites(self):
        url=plano_bcra(inicio="2026-10-01",fim="2026-10-02")
        self.assertIn("/Monetarias/1?",url)
        self.assertIn("Desde=2026-10-01",url)
        for kw in ({"variavel":0}, {"variavel":999}, {"variavel":"1"}):
            with self.assertRaises(ErroColetor):
                plano_bcra(inicio="2026-10-01",fim="2026-10-02",**kw)
    def test_parse_schema_valores_e_paginacao(self):
        rows,truncado=parse_bcra(json.dumps(DOC).encode())
        self.assertEqual(len(rows),2)
        self.assertFalse(truncado)
        self.assertIsNone(rows[0]["unidade"])
        doc=dict(DOC,metadata={"resultset":{"count":500}})
        self.assertTrue(parse_bcra(json.dumps(doc).encode())[1])
        with self.assertRaises(ErroColetor):
            parse_bcra(json.dumps(dict(DOC,results=[{"idVariable":2,"detalle":[]}])).encode())
    def test_bcra_to_sqlite_jsonl(self):
        with tempfile.TemporaryDirectory() as p:
            path=Path(p)
            url=plano_bcra(inicio="2026-10-01",fim="2026-10-02")
            args=dict(inicio="2026-10-01",fim="2026-10-02",banco=path/"db.sqlite",
                      raw_dir=path/"raw",executar=True,cliente=Fake(url,json.dumps(DOC).encode()),instante=T)
            a=coletar_bcra(**args)
            b=coletar_bcra(**args)
            self.assertEqual(a["novas_observacoes"],2)
            self.assertEqual(b["novas_observacoes"],0)
            self.assertTrue(a["unidade_pendente"])
            out=exportar_jsonl(banco=path/"db.sqlite",destino=path/"data.jsonl")
            self.assertEqual(out["observacoes"],2)
            self.assertEqual(len((path/"data.jsonl").read_text().splitlines()),2)

if __name__=="__main__":
    unittest.main()
