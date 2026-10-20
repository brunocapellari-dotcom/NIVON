"""Coletor NASA testado com opener injetado; nenhum teste consulta a rede."""
import json
import unittest
from copy import deepcopy
from nivon.nasa_power_diario import planejar_power
from nivon.grade_meteorologica_store import abrir_grade,grade_asof
from nivon.nasa_power_captura_manual import capturar_power_manual,ErroCapturaPower

LICENCA="NASA POWER - permissao COLETA e ARMAZENAMENTO, caso de teste"
FLAGS=frozenset({"COLETA","ARMAZENAMENTO"})

def plano():
    return planejar_power(latitude=-12.54,longitude=-55.72,
        inicio="2025-01-01",fim="2025-01-02",
        parametros=("PRECTOTCORR","T2M_MIN","T2M_MAX"))

def bytes_nasa(chuva=10):
    return json.dumps({
        "type":"Feature",
        "geometry":{"type":"Point","coordinates":[-55.7,-12.5,300]},
        "properties":{"parameter":{
            "PRECTOTCORR":{"20250101":chuva,"20250102":-999},
            "T2M_MIN":{"20250101":20,"20250102":21},
            "T2M_MAX":{"20250101":30,"20250102":31}
        }}}).encode()

class Response:
    status=200
    def __init__(self,raw,url,content_type="application/json"):
        self.raw=raw
        self.url=url
        self.headers={"Content-Type":content_type}
    def geturl(self):return self.url
    def read(self,n):return self.raw[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False

class FakeTransport:
    def __init__(self,raw,*,host=None,mime="application/json"):
        self.raw=raw;self.host=host;self.mime=mime;self.calls=0
    def open(self,req,timeout):
        self.calls+=1
        return Response(self.raw,self.host or req.full_url,self.mime)

class TestPowerManual(unittest.TestCase):
    def setUp(self):
        self.db=abrir_grade()
        self.addCleanup(self.db.close)

    def executar(self,transport,**kwargs):
        return capturar_power_manual(self.db,plano=plano(),autorizar_http=True,
            autorizacoes=FLAGS,evidencia_licenca=LICENCA,
            transporte=transport,**kwargs)

    def test_rede_explicitamente_desligada(self):
        x=FakeTransport(bytes_nasa())
        with self.assertRaises(PermissionError):
            capturar_power_manual(self.db,plano=plano(),transporte=x)
        self.assertEqual(x.calls,0)

    def test_download_manual_valido_persiste_e_metadados_geograficos(self):
        x=FakeTransport(bytes_nasa())
        o=self.executar(x)
        self.assertEqual(x.calls,1)
        self.assertEqual(o["estado"],"CAPTURADO_E_VERIFICADO_LOCAL")
        self.assertEqual(o["valores"],6)
        self.assertFalse(o["publicacao_conhecida"])
        s=self.db.execute("SELECT latitude_grade,longitude_grade,coordenada_lat,coordenada_lon FROM grade_edicao").fetchone()
        self.assertAlmostEqual(s["latitude_grade"],-12.5)
        self.assertAlmostEqual(s["longitude_grade"],-55.7)
        self.assertAlmostEqual(s["coordenada_lat"],-12.54)
        self.assertAlmostEqual(s["coordenada_lon"],-55.72)
        self.assertEqual(grade_asof(self.db,consulta_sha256=o["consulta_sha256"],
            parametro="PRECTOTCORR",inicio="2025-01-01",fim="2025-01-02",
            corte_publicacao="2026-01-01T00:00:00Z",
            corte_coleta="2026-01-01T00:00:00Z"),[])

    def test_cache_sem_http_novo(self):
        self.executar(FakeTransport(bytes_nasa()))
        x=FakeTransport(bytes_nasa(chuva=12))
        out=self.executar(x)
        self.assertEqual(out["estado"],"CACHE_LOCAL_SEM_HTTP")
        self.assertEqual(out["requisições_http"],0)
        self.assertEqual(x.calls,0)

    def test_revisao_forcada_tem_duas_versoes(self):
        self.executar(FakeTransport(bytes_nasa()))
        self.executar(FakeTransport(bytes_nasa(chuva=12)),revisao_explicita=True)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM grade_edicao").fetchone()[0],2)

    def test_sem_direitos_nao_consulta(self):
        x=FakeTransport(bytes_nasa())
        with self.assertRaises(PermissionError):
            capturar_power_manual(self.db,plano=plano(),autorizar_http=True,
                transporte=x)
        self.assertEqual(x.calls,0)

    def test_url_hostil_e_query_falsa_bloqueadas(self):
        p=deepcopy(plano());p["url"]=p["url"].replace(
            "power.larc.nasa.gov","power.larc.nasa.gov.attacker.invalid")
        with self.assertRaises(ErroCapturaPower):
            capturar_power_manual(self.db,plano=p,autorizar_http=True,
                autorizacoes=FLAGS,evidencia_licenca=LICENCA,
                transporte=FakeTransport(bytes_nasa()))
        p=deepcopy(plano());p["url"]+="&bad=1"
        with self.assertRaises(ErroCapturaPower):
            capturar_power_manual(self.db,plano=p,autorizar_http=True,
                autorizacoes=FLAGS,evidencia_licenca=LICENCA,
                transporte=FakeTransport(bytes_nasa()))

    def test_mime_ruim_ou_redirecionamento_bloqueado(self):
        for transport in (
            FakeTransport(bytes_nasa(),mime="text/html"),
            FakeTransport(bytes_nasa(),host="https://evil.invalid/redir")
        ):
            with self.assertRaises(ErroCapturaPower):
                self.executar(transport)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM grade_edicao").fetchone()[0],0)

    def test_resposta_de_outra_regiao_bloqueia_persistencia(self):
        obj=json.loads(bytes_nasa())
        obj["geometry"]["coordinates"]=[25,25]
        with self.assertRaises(Exception):
            self.executar(FakeTransport(json.dumps(obj).encode()))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM grade_edicao").fetchone()[0],0)

if __name__=="__main__":unittest.main()
