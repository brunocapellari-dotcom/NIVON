"""Sonda BCB SGS11: validates recent real-world contract with mock transport."""
from datetime import datetime, timezone
import hashlib
import io
import json
import unittest
from contextlib import redirect_stdout
from nivon.sonda_sgs11 import validar_sonda, main
from nivon.sgs11_gcp import URL

FIXTURE=b'[{"data":"22/10/2026","valor":"0,055"}]'
HOJE=datetime(2026,10,23,18,tzinfo=timezone.utc)

class Http:
    def __init__(self,payload=FIXTURE):self.payload=payload
    def open(self,req,timeout):
        assert req.full_url==URL and timeout>0
        raw=self.payload
        class Resp:
            status=200
            headers={"Content-Type":"application/json"}
            def geturl(self):return URL
            def read(self,n):return raw[:n]
            def __enter__(self):return self
            def __exit__(self,*args):return False
        return Resp()

class TestSondaBCB(unittest.TestCase):
    def test_recent_valid(self):
        r=validar_sonda(agora=HOJE,abridor=Http())
        self.assertEqual(r["estado"],"BCB_SGS11_ORIGEM_REAL_VERIFICADA")
        self.assertEqual(r["idade_dias"],1)
        self.assertEqual(r["sha256_http"],hashlib.sha256(FIXTURE).hexdigest())
        self.assertEqual(r["valor"],"0.055")
        self.assertFalse(r["gcs_executado"])
        self.assertFalse(r["bigquery_executado"])
        self.assertFalse(r["publicacao_comprovada"])
    def test_outdated_fails_as_outdated_not_valid(self):
        r=validar_sonda(agora=HOJE,abridor=Http(
            b'[{"data":"01/10/2026","valor":"0,055"}]'))
        self.assertEqual(r["estado"],"FONTE_RESPONDE_MAS_ATRASADA")
        self.assertGreater(r["idade_dias"],14)
    def test_wrong_contract_fails(self):
        with self.assertRaises(ValueError):
            validar_sonda(agora=HOJE,abridor=Http(
                b'{"erro":"dados indisponiveis"}'))
    def test_cli_is_inert_by_default(self):
        buf=io.StringIO()
        with redirect_stdout(buf):ret=main([])
        self.assertEqual(ret,0)
        self.assertEqual(json.loads(buf.getvalue())["estado"],"PLANO_SEM_REDE")
    def test_invalid_arguments(self):
        with self.assertRaises(ValueError):validar_sonda(agora=HOJE,abridor=Http(),max_atraso_dias=100)
        with self.assertRaises(ValueError):validar_sonda(agora=datetime(2026,10,23),abridor=Http())

if __name__=="__main__":unittest.main()
