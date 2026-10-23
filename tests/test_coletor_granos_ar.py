import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from nivon.coletor_granos_ar import (
    ENDPOINTS, plano_granos_ar, parse_granos_ar, coletar_granos_ar
)
from nivon.coletores_dados_reais import ErroColetor

T=datetime(2026,10,22,tzinfo=timezone.utc)

class Resp:
    status=200
    headers={"Content-Type":"application/json"}
    def __init__(self,url,body):
        self.url=url;self.body=body
    def geturl(self): return self.url
    def read(self,n): return self.body[:n]
    def __enter__(self): return self
    def __exit__(self,*args): return False

class Fake:
    def __init__(self,url,body):
        self.url=url;self.body=body
    def open(self,request,timeout=30):
        assert request.full_url==self.url
        return Resp(self.url,self.body)

class GranosArTest(unittest.TestCase):
    def test_12_rotas_sem_resumen_textual(self):
        self.assertEqual(len(ENDPOINTS),13)
        with self.assertRaises(ErroColetor):
            plano_granos_ar(endpoint="resumen")
        with self.assertRaises(ErroColetor):
            plano_granos_ar(endpoint="https://evil.example")
        self.assertIn("dias=30",plano_granos_ar(endpoint="pizarra/historico"))

    def test_pizarra_normaliza_moedas_separadamente(self):
        d={"meta":{"fuente":"granos.ar","generado_en":"2026-10-22T12:00:00Z"},
          "data":{"fecha":"2026-10-22","granos":{
            "soja":{"ars_tn":452000,"usd_tn":318.2},
            "maiz":{"ars_tn":210000,"usd_tn":140.1}}}}
        raw=json.dumps(d).encode()
        rows=parse_granos_ar(raw,endpoint="pizarra")
        self.assertEqual(len(rows),4)
        self.assertEqual(set(r["unidade"] for r in rows),{"ARS/t","USD/t"})
        with tempfile.TemporaryDirectory() as p:
            path=Path(p)
            url=plano_granos_ar(endpoint="pizarra")
            args=dict(endpoint="pizarra",banco=path/"db.sqlite",raw_dir=path/"raw",
                    executar=True,cliente=Fake(url,raw),instante=T)
            result=coletar_granos_ar(**args)
            self.assertEqual(result["novas_observacoes"],4)
            self.assertEqual(coletar_granos_ar(**args)["novas_observacoes"],0)
            self.assertFalse(result["validacao_primaria"])
            self.assertEqual(result["tipo_fonte"],"SECUNDARIA")

    def test_sem_prazos_falsos_ou_fonte_trocada(self):
        for obj in ({"data":{"fecha":"2026-10-22","granos":{}}},
            {"meta":{"fuente":"outra"},"data":{"fecha":"2026-10-22","granos":{}}},
            {"meta":{"fuente":"granos.ar"},"data":{"fecha":"2036-20-99","granos":{}}},
            {"meta":{"fuente":"granos.ar"},"data":{"fecha":"2026-10-22",
                "granos":{"soja":{"ars_tn":"452000"}}}}):
            with self.subTest(obj=obj),self.assertRaises(ErroColetor):
                parse_granos_ar(json.dumps(obj).encode(),endpoint="pizarra")
        with self.assertRaises(PermissionError):
            coletar_granos_ar(endpoint="pizarra",banco="db",raw_dir="raw")

if __name__=="__main__":
    unittest.main()
