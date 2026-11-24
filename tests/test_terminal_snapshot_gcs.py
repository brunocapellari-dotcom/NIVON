"""Verificacao ponta a ponta GCS privado -> terminal interno, SEM rede externa."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import urlopen
import json
import threading
import unittest

from nivon.terminal_snapshot_gcs import (
    BUCKET, OBJECT, REGION, EstadoSnapshot, LeituraSnapshotBloqueada,
    ler_gcs,
)
from nivon.terminal_web import TerminalState, servidor

NOW = datetime(2026, 10, 25, 20, 30, tzinfo=timezone.utc)


def payload(gerado=None):
    return {
        "schema": "nivon.portal.interno.v1",
        "modo": "INTERNO_SHADOW",
        "estado": "DADOS_REAIS_EM_REVISAO_INTERNA_NAO_HOMOLOGADOS",
        "gerado_em": (gerado or NOW).isoformat(),
        "fontes_consultadas": ["ANTT_SIADE_ORIGEM_DESTINO", "LINEUP_IMBITUBA"],
        "indicadores": [{
            "id": "ferrovia_tu", "grupo": "logistica",
            "titulo": "Ferrovia MT", "valor": "10200.75", "unidade": "TU",
            "referencia": "2026-08", "fonte": "ANTT/SIADE",
            "natureza": "OBSERVADO_DECLARADO",
            "ressalva": "Origem por estação, sem transbordo confirmado.",
            "publicavel": False,
        }, {
            "id": "lineup_imbituba", "grupo": "maritimo",
            "titulo": "Imbituba, IDs de programação", "valor": "2",
            "unidade": "IDs", "referencia": "outubro/2026",
            "fonte": "Line-up institucional", "natureza": "INFORMADO_PROGRAMADO",
            "ressalva": "Não equivale a navios operados ou carga embarcada.",
            "publicavel": False,
        }],
        "avisos": ["Programação diferente de realizado."],
        "publicavel": False, "redistribuicao_autorizada": False,
        "precos_homologados": False, "go_live_publico": False,
        "nota": "Uso exclusivamente interno",
    }


class Blob:
    def __init__(self, data, metadata=None, size=None, generation=17):
        self.data=data
        self.metadata=metadata if metadata is not None else {
            "nivon_modo":"INTERNO_SHADOW","sha256":sha256(data).hexdigest()
        }
        self.size=len(data) if size is None else size
        self.generation=generation
        self.calls=[]
    def reload(self):
        self.calls.append("HEAD")
    def download_as_bytes(self, **kwargs):
        self.calls.append(("GET", kwargs))
        return self.data


class Bucket:
    def __init__(self, blob, loc=REGION, pap="enforced"):
        self._blob=blob
        self.location=loc
        self.iam_configuration=SimpleNamespace(public_access_prevention=pap)
        self.paths=[]
    def blob(self,path):
        self.paths.append(path)
        return self._blob


class Storage:
    def __init__(self, bucket):
        self._bucket=bucket
        self.called=[]
    def get_bucket(self,name):
        self.called.append(name)
        return self._bucket


def fake_snapshot(**kw):
    doc=payload(kw.pop("gerado",None))
    doc.update(kw)
    return json.dumps(doc,ensure_ascii=False,separators=(",",":")).encode("utf8")


class GCSPrivateTests(unittest.TestCase):
    def read(self, data=None, **args):
        data = fake_snapshot() if data is None else data
        blob=Blob(data, **{k:args[k] for k in ("metadata","size","generation") if k in args})
        bucket=Bucket(blob,loc=args.get("loc",REGION),pap=args.get("pap","enforced"))
        storage=Storage(bucket)
        return ler_gcs(storage_client=storage,relogio=lambda:args.get("now",NOW)),storage,bucket,blob

    def test_snapshot_real_privado_e_sha_com_controles(self):
        item,storage,bucket,blob=self.read()
        self.assertEqual(item["frescor_snapshot"],"ATUAL")
        self.assertEqual(item["origem_terminal"],"GCS_PRIVADO_COM_SHA256")
        self.assertFalse(item["go_live_publico"])
        self.assertEqual(len(item["indicadores"]),2)
        self.assertEqual(storage.called,[BUCKET])
        self.assertEqual(bucket.paths,[OBJECT])
        self.assertEqual(blob.calls,["HEAD",("GET",{"if_generation_match":17})])

    def test_bloqueia_bucket_publico_ou_regiao_diferente(self):
        for kw in ({"pap":"inherited"},{"loc":"us-central1"}):
            with self.subTest(kw=kw),self.assertRaises(LeituraSnapshotBloqueada):
                self.read(**kw)

    def test_bloqueia_hash_diferente_payload_excessivo_e_versao_invalida(self):
        badmeta={"nivon_modo":"INTERNO_SHADOW","sha256":"0"*64}
        for kw in ({"metadata":badmeta},{"size":2_000_001},{"generation":0}):
            with self.subTest(kw=kw),self.assertRaises(LeituraSnapshotBloqueada):
                self.read(**kw)

    def test_nao_mostra_snapshot_antigo_ou_futuro(self):
        for data in (fake_snapshot(gerado=NOW-timedelta(days=3)),
                     fake_snapshot(gerado=NOW+timedelta(minutes=10))):
            with self.assertRaises(LeituraSnapshotBloqueada):
                self.read(data)

    def test_nao_apresenta_publicavel_ou_json_duplicado(self):
        bad=fake_snapshot(go_live_publico=True)
        with self.assertRaises(LeituraSnapshotBloqueada):
            self.read(bad)
        duplicate=fake_snapshot().replace(b'"go_live_publico":false',
             b'"go_live_publico":false,"go_live_publico":false')
        with self.assertRaises(LeituraSnapshotBloqueada):
            self.read(duplicate)

    def test_cache_nao_serve_dados_velhos_quando_renovacao_falha(self):
        now=[0.0]
        calls=[0]
        doc={**payload(),"frescor_snapshot":"ATUAL"}
        def reader():
            calls[0]+=1
            if calls[0]>1:
                raise LeituraSnapshotBloqueada("falha interna")
            return doc
        cache=EstadoSnapshot(reader=reader,relogio=lambda:now[0])
        cache.obter();cache.obter()
        self.assertEqual(calls[0],1)
        now[0]=301.0
        with self.assertRaises(LeituraSnapshotBloqueada):
            cache.obter()
        self.assertIsNone(cache._data)

    def test_um_unico_servico_http_com_painel_real_e_ferrovia(self):
        doc={**payload(),"frescor_snapshot":"ATUAL"}
        rail={"estado":"ANTT_SERIE_OBSERVADA_DECLARADA","serie":[]}
        server=ThreadingHTTPServer(("127.0.0.1",0),servidor(
            TerminalState(consulta=lambda:rail),
            snapshot=EstadoSnapshot(reader=lambda:doc)))
        task=threading.Thread(target=server.serve_forever,daemon=True);task.start()
        url=f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(url+"/portal") as r:
                html=r.read().decode("utf8")
                self.assertIn("Mercado físico e bolsas",html)
                self.assertIn("Logística terrestre",html)
            with urlopen(url+"/assets/portal.js") as r:
                self.assertIn("/api/v1/painel",r.read().decode("utf8"))
            with urlopen(url+"/api/v1/painel") as r:
                result=json.load(r)
                self.assertEqual(result["indicadores"][0]["valor"],"10200.75")
                self.assertFalse(result["publicavel"])
                self.assertEqual(r.headers["Cache-Control"],"no-store")
            with urlopen(url+"/readyz") as r:
                self.assertEqual(json.load(r)["status"],"PAINEL_PRIVADO_COM_DADOS_REAIS")
            with urlopen(url+"/api/v1/ferrovia") as r:
                self.assertEqual(json.load(r)["estado"],"ANTT_SERIE_OBSERVADA_DECLARADA")
        finally:
            server.shutdown();server.server_close();task.join(timeout=3)

    def test_m1_valida_antt_no_bigquery_sem_obrigar_maritimo(self):
        """O snapshot GCS segue testado, mas não bloqueia o primeiro M1 ANTT."""
        from pathlib import Path
        script=(Path(__file__).resolve().parents[1] /
                "scripts/deploy_terminal_privado.sh").read_text(encoding="utf-8")
        self.assertIn("vw_antt_ferrovia_od_atual", script)
        self.assertIn("VIEW_FERROVIA_NAO_HABILITADA", script)
        self.assertLess(script.index("VIEW_FERROVIA_NAO_HABILITADA"),
                        script.index("gcloud builds submit"))
        self.assertNotIn("from nivon.terminal_snapshot_gcs import ler_gcs", script)
        self.assertNotIn("GO_LIVE_BLOQUEADO_SEM_DADOS_MARITIMOS_REAIS", script)
        self.assertIn("--iap", script)
        self.assertIn("--no-allow-unauthenticated", script)
        self.assertIn("--min-instances=0", script)
        self.assertIn("--max-instances=1", script)

    def test_falha_leitura_retorna_503_sem_informacao_privada(self):
        def broken():
            raise RuntimeError("SECRET_BQ_IAM_DONT_LEAK")
        server=ThreadingHTTPServer(("127.0.0.1",0),servidor(
            TerminalState(consulta=lambda:{"estado":"ANTT_SERIE_OBSERVADA_DECLARADA"}),
            snapshot=EstadoSnapshot(reader=broken)))
        task=threading.Thread(target=server.serve_forever,daemon=True);task.start()
        try:
            url=f"http://127.0.0.1:{server.server_port}"
            for route in ("/api/v1/painel","/readyz"):
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(url+route)
                self.assertEqual(ctx.exception.code,503)
                self.assertNotIn("SECRET_BQ_IAM_DONT_LEAK",ctx.exception.read().decode())
        finally:
            server.shutdown();server.server_close();task.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
