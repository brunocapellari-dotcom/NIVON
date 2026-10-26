"""Portal em Cloud Run privado: testes adversariais, sem acesso externo."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import unittest

from nivon.portal_gcs import LeitorSnapshotGCS, criar_app_cloud, OBJECT
from nivon.portal_interno import ErroPortal
from test_portal_interno import amostra, CUT
from nivon.portal_interno import montar_snapshot


class Blob:
    def __init__(self, raw):
        self.bytes=raw
        self.generation=15
        self.size=len(raw)
        self.content_type="application/json"
        self.metadata={"nivon_modo":"INTERNO_SHADOW","sha256":sha256(raw).hexdigest()}
        self.calls=0
    def reload(self, **kwargs):
        self.calls+=1
        assert kwargs["timeout"]==15
    def download_as_bytes(self, **kwargs):
        assert kwargs["if_generation_match"]==self.generation
        assert kwargs["checksum"]=="crc32c"
        return self.bytes

class Bucket:
    location="southamerica-east1"
    def __init__(self, blob):
        self._blob=blob
    def blob(self, name):
        assert name==OBJECT
        return self._blob

class Client:
    def __init__(self, blob):
        self.b=Bucket(blob)
    def get_bucket(self, name):
        assert name=="nivon-data-raw-2026"
        return self.b

def snapshot():
    doc=montar_snapshot(amostra(),gerado_em=CUT)
    doc["gerado_em"]=datetime.now(timezone.utc).isoformat()
    return json.dumps(doc,ensure_ascii=False).encode("utf-8")

def request(app, path, method="GET"):
    meta={}
    def start(status, hdr):
        meta["status"]=status;meta["headers"]=dict(hdr)
    body=b"".join(app({"PATH_INFO":path,"REQUEST_METHOD":method},start))
    return meta["status"],meta["headers"],body

class PortalGcsTests(unittest.TestCase):
    def test_snapshot_correto_no_servidor_e_cache(self):
        blob=Blob(snapshot())
        reader=LeitorSnapshotGCS(projeto="nivon-data",bucket="nivon-data-raw-2026",
                                 cliente_factory=lambda **kw:Client(blob),
                                 relogio=lambda:123.0,cache_segundos=60)
        doc=reader.carregar()
        self.assertEqual(doc["modo"],"INTERNO_SHADOW")
        self.assertIs(reader.carregar(),doc)
        self.assertEqual(blob.calls,1)
        env={"K_SERVICE":"nivon-portal-interno","GOOGLE_CLOUD_PROJECT":"nivon-data",
             "NIVON_PORTAL_GCS_BUCKET":"nivon-data-raw-2026",
             "NIVON_PORTAL_PRIVATE_INGRESS_APPROVED":"true",
             "NIVON_PORTAL_GCS_READ_APPROVED":"true",
             "NIVON_PORTAL_PRIVATE_BUCKET_REVIEWED":"true"}
        app=criar_app_cloud(env=env,cliente_factory=lambda **kw:Client(blob),
                           relogio=lambda:123.0)
        self.assertEqual(request(app,"/healthz")[0],"200 OK")
        self.assertEqual(request(app,"/")[0],"200 OK")
        self.assertEqual(request(app,"/readyz")[0],"200 OK")
        status,headers,payload=request(app,"/api/v1/painel")
        self.assertEqual(status,"200 OK")
        self.assertEqual(headers["Cache-Control"],"no-store")
        self.assertFalse(json.loads(payload)["publicavel"])
        self.assertEqual(request(app,"/api/v1/painel","POST")[0],"405 Method Not Allowed")

    def test_erro_de_storage_falha_fechada(self):
        b=Blob(snapshot())
        b.metadata["sha256"]="1"*64
        class Clock:
            value=100
            def __call__(self):return self.value
        clock=Clock()
        reader=LeitorSnapshotGCS(projeto="nivon-data",bucket="nivon-data-raw-2026",
                  cliente_factory=lambda **kw:Client(b),relogio=clock,cache_segundos=10)
        with self.assertRaises(ErroPortal):reader.carregar()
        b.metadata["sha256"]=sha256(b.bytes).hexdigest()
        reader.carregar()
        self.assertEqual(b.calls,2)
        clock.value=112
        b.bytes=b'{"erro":"invalido"}'
        b.size=len(b.bytes)
        b.metadata["sha256"]=sha256(b.bytes).hexdigest()
        with self.assertRaises(ErroPortal):reader.carregar()
        # Cache positivo anterior descartado; nao usar dado obsoleto.
        with self.assertRaises(ErroPortal):reader.carregar()
        self.assertEqual(b.calls,4)

    def test_metadados_inseguros_ou_limites(self):
        cases=[
            lambda b:setattr(b,"size",2_000_001),
            lambda b:setattr(b,"generation",0),
            lambda b:setattr(b,"content_type","text/plain"),
            lambda b:b.metadata.update(nivon_modo="PUBLICO"),
            lambda b:b.metadata.update(sha256="nao e hash"),
        ]
        for mutate in cases:
            b=Blob(snapshot())
            mutate(b)
            with self.subTest(mutacao=mutate),self.assertRaises(ErroPortal):
                LeitorSnapshotGCS(projeto="nivon-data",bucket="nivon-data-raw-2026",
                    cliente_factory=lambda **kw:Client(b),cache_segundos=0).carregar()

    def test_runtime_exige_iam_esperado_sem_bypass(self):
        env={"K_SERVICE":"nivon-portal-interno","GOOGLE_CLOUD_PROJECT":"nivon-data",
             "NIVON_PORTAL_GCS_BUCKET":"nivon-data-raw-2026",
             "NIVON_PORTAL_PRIVATE_INGRESS_APPROVED":"true",
             "NIVON_PORTAL_GCS_READ_APPROVED":"true",
             "NIVON_PORTAL_PRIVATE_BUCKET_REVIEWED":"true"}
        for k in env:
            broken=dict(env);broken[k]="invalid"
            with self.subTest(campo=k),self.assertRaises(ErroPortal):
                criar_app_cloud(env=broken)
        with self.assertRaises(ErroPortal):
            LeitorSnapshotGCS(projeto="outro",bucket="nivon-data-raw-2026")
        with self.assertRaises(ErroPortal):
            LeitorSnapshotGCS(projeto="nivon-data",bucket="bucket-publico")

    def test_payload_antigo_sinaliza_defasagem(self):
        b=Blob(snapshot())
        doc=json.loads(b.bytes)
        doc["gerado_em"]=(datetime.now(timezone.utc)-timedelta(days=4)).isoformat()
        b.bytes=json.dumps(doc).encode()
        b.size=len(b.bytes)
        b.metadata["sha256"]=sha256(b.bytes).hexdigest()
        env={"K_SERVICE":"nivon-portal-interno","GOOGLE_CLOUD_PROJECT":"nivon-data",
             "NIVON_PORTAL_GCS_BUCKET":"nivon-data-raw-2026",
             "NIVON_PORTAL_PRIVATE_INGRESS_APPROVED":"true",
             "NIVON_PORTAL_GCS_READ_APPROVED":"true",
             "NIVON_PORTAL_PRIVATE_BUCKET_REVIEWED":"true"}
        app=criar_app_cloud(env=env,cliente_factory=lambda **kw:Client(b))
        self.assertEqual(request(app,"/readyz")[0],"503 Service Unavailable")
        self.assertEqual(json.loads(request(app,"/api/v1/painel")[2])["frescor_snapshot"],"DEFASADO")

if __name__=="__main__":
    unittest.main()
