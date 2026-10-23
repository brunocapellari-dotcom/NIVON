"""Tests offline de transporte CSV Argentina (somente fixtures sinteticas)."""
from datetime import datetime, timezone
from hashlib import sha256
import unittest

from nivon.argentina_agricultura import ErroArgentina
from nivon.argentina_download_csv import baixar_csv_candidato, validar_url_download

AGORA=datetime(2026,10,22,tzinfo=timezone.utc)
URL='https://datos.magyp.gob.ar/dataset/soja-siembra-cosecha-produccion-rendimiento/resource/ba694aa3-99d2-4d7d-9936-60f88e36ad9a/download/soja.csv'
CSV=('cultivo,anio,campania,provincia,provincia_id,departamento,departamento_id,superficie_sembrada_ha,superficie_cosechada_ha,produccion_tm,rendimiento_kgxha\n'
     'Soja,2025,2025/26,Cordoba,014,Capital,00010,100,90,270,3000\n').encode()

class _Resposta:
    def __init__(self,body=CSV,url=URL,mime='text/csv',status=200):
        self.body=body
        self.url=url
        self.headers={'Content-Type':mime}
        self.status=status
    def geturl(self):return self.url
    def read(self,n):return self.body[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False

class _Abridor:
    def __init__(self,response):self.response=response
    def open(self,req,timeout):return self.response

class TestArgentinaDownloadCSV(unittest.TestCase):
    def test_baixar_mock_verifica_sha_e_sem_publicar(self):
        r=baixar_csv_candidato(recurso='soja',url=URL,executar=True,
            direitos_coleta_verificados=True,abridor=_Abridor(_Resposta()),
            coletado_em=AGORA)
        self.assertEqual(r['sha256'],sha256(CSV).hexdigest())
        self.assertEqual(r['bytes'],len(CSV))
        self.assertEqual(r['raw'],CSV)
        self.assertIn('NAO_PUBLICADO',r['estado'])

    def test_bloqueado_sem_licenca(self):
        with self.assertRaises(PermissionError):
            baixar_csv_candidato(recurso='soja',url=URL,executar=True,abridor=_Abridor(_Resposta()))
        with self.assertRaises(PermissionError):
            baixar_csv_candidato(recurso='soja',url=URL,direitos_coleta_verificados=True)

    def test_url_insegura_rejeitada(self):
        for u in (
            'http://datos.magyp.gob.ar/dataset/a.csv',
            'https://127.0.0.1/dataset/soja.csv',
            'https://datos.magyp.gob.ar.evil.tld/dataset/soja.csv',
            'https://datos.magyp.gob.ar/dataset/../admin.csv',
            'https://datos.magyp.gob.ar/dataset/grafico',
            'https://datos.magyp.gob.ar/dataset/soja.csv?file=abc',
            'https://datos.magyp.gob.ar@evil.tld/dataset/soja.csv',
        ):
            with self.subTest(u=u):
                with self.assertRaises(ErroArgentina):
                    validar_url_download(u,'soja')

    def test_rejeita_waf_e_redirect_e_mime(self):
        for resp in (
            _Resposta(body=b'<html>Conab</html>'),
            _Resposta(body=b'not,csv\n1,2\n'),
            _Resposta(url='https://evil.tld/soja.csv'),
            _Resposta(mime='text/html'),
            _Resposta(body=b''),
            _Resposta(status=403),
        ):
            with self.subTest(resp=repr(resp)):
                with self.assertRaises(ErroArgentina):
                    baixar_csv_candidato(recurso='soja',url=URL,executar=True,
                      direitos_coleta_verificados=True,abridor=_Abridor(resp),coletado_em=AGORA)

if __name__=='__main__':
    unittest.main()
