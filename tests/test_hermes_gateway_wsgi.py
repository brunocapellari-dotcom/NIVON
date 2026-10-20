"""HTTP contract with OIDC verifier injected: offline mock, no server/keys."""
import hashlib
import io
import json
import unittest
from datetime import datetime, timezone

from nivon.conab_agrobr import normalizar_progresso
from nivon.hermes_adapter import NivonProjectAdapter
from nivon.hermes_gateway_wsgi import criar_gateway_hermes, ErroGateway
from nivon.progresso_store import abrir_progresso, gravar_progresso


AUDIENCE="https://nivon-internal.example.test"
SUBJECT="sa-verified-1234"
TOKEN="a"*64
NOW="2026-10-20T12:00:00+00:00"
SOURCE="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture"
CLAIMS={"iss":"https://accounts.google.com","aud":AUDIENCE,"sub":SUBJECT}


class TestHermesGateway(unittest.TestCase):
    def setUp(self):
        self.db=abrir_progresso()
        r=normalizar_progresso([{
            "cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
            "uf":"MT","semana_atual":"2026-10-16","pct_semana_atual":0.43,
        }],fonte_url=SOURCE,
        coletado_em=datetime(2026,10,19,12,tzinfo=timezone.utc),
        publicado_em="2026-10-18T13:00:00+00:00")
        gravar_progresso(self.db,r,evidence_id="OIDC_GATEWAY_TESTE",
                         direitos_confirmados=True)
        self.calls=[]
        self.subject=None
        self.claims=dict(CLAIMS)
        def verificador(token,audience):
            self.calls.append(("verifier",token,audience))
            if token!=TOKEN or audience!=AUDIENCE:
                raise PermissionError("invalid")
            return dict(self.claims)
        def fabrica(subject):
            self.calls.append(("factory",subject))
            self.subject=subject
            return NivonProjectAdapter(
                autorizador=lambda scope:subject==SUBJECT and scope=="NIVON_READ",
                conab=self.db,
                fontes={"CONAB":{
                    "status_direitos":"APROVADA",
                    "operacoes":["LEITURA","PUBLICACAO_DERIVADA"],
                }},
            )
        self.app=criar_gateway_hermes(
            audience=AUDIENCE,
            sujeitos_permitidos=frozenset({SUBJECT}),
            fabrica_adaptador=fabrica,verificar=verificador)

    def tearDown(self):
        self.db.close()

    def post(self,item=None,*,token=TOKEN,path="/v1/nivon/query",
             method="POST",ctype="application/json",body=None,headers=None):
        data=body if body is not None else json.dumps(
            item or {"capability":"safra.progress.read","payload":{
                "cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
                "uf":"MT","semana":"2026-10-16","gerado_em":NOW,
            }},separators=(",",":")).encode()
        env={
            "PATH_INFO":path,"REQUEST_METHOD":method,"CONTENT_TYPE":ctype,
            "CONTENT_LENGTH":str(len(data)),"wsgi.input":io.BytesIO(data),
        }
        if token is not None:
            env["HTTP_AUTHORIZATION"]="Bearer "+token
        if headers: env.update(headers)
        response=[]
        result=b"".join(self.app(env,lambda status,h:response.append((status,h))))
        return response[0][0],json.loads(result),dict(response[0][1])

    def test_success_read_only_with_verified_claims(self):
        status,body,headers=self.post()
        self.assertEqual(status,"200 OK")
        self.assertEqual(body["status"],"CONSULTA_READ_ONLY")
        self.assertEqual(body["result"]["status"],"INDICADOR_VERIFICADO_TEMPO")
        self.assertIn("43.0%",body["result"]["indicador"]["valor"])
        self.assertEqual(self.calls[0],("verifier",TOKEN,AUDIENCE))
        self.assertEqual(self.calls[1],("factory",SUBJECT))
        self.assertEqual(headers["Cache-Control"],"no-store")

    def test_missing_or_malformed_token_rejected_before_factory(self):
        for token in (None,"short","a"*15):
            with self.subTest(token=token):
                status,body,_=self.post(token=token)
                self.assertEqual(status,"401 Unauthorized")
        self.assertEqual(self.calls,[])

    def test_wrong_audience_or_issuer_or_subject_rejected(self):
        for k,value in (("aud","https://wrong.example"),("iss","evil.example"),
                        ("sub","another-service-account")):
            with self.subTest(k=k):
                self.claims={**CLAIMS,k:value}
                status,body,_=self.post()
                self.assertEqual(status,"403 Forbidden")
                self.assertEqual(body["status"],"ACESSO_NEGADO")
        self.assertFalse(any(x[0]=="factory" for x in self.calls))

    def test_verification_failure_not_leaked(self):
        status,body,_=self.post(token="b"*64)
        self.assertEqual(status,"403 Forbidden")
        self.assertNotIn("invalid",str(body))
        self.assertIsNone(self.subject)

    def test_execute_action_not_exposed(self):
        status,body,_=self.post(item={
            "capability":"send_whatsapp",
            "payload":{"gerado_em":NOW,"force":True},
        })
        self.assertEqual(status,"400 Bad Request")
        self.assertNotIn("send_whatsapp",str(body))

    def test_trust_boundary_forbidden_payload(self):
        status,body,_=self.post(item={
            "capability":"safra.progress.read",
            "payload":{
                "gerado_em":NOW,"sql":"DROP TABLE progresso_observacoes"
            },
        })
        self.assertEqual(status,"400 Bad Request")
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM progresso_observacoes").fetchone()[0],1)

    def test_disallow_oversized_body(self):
        status,body,_=self.post(body=b"x"*65537)
        self.assertEqual(status,"413 Content Too Large")
        self.assertFalse(any(x[0]=="factory" for x in self.calls))

    def test_disallow_wrong_method_path_and_media_type(self):
        for kw,expected in (
            ({"method":"GET"},"405 Method Not Allowed"),
            ({"path":"/v1/nivon/execute"},"404 Not Found"),
            ({"ctype":"text/plain"},"415 Unsupported Media Type"),
        ):
            with self.subTest(kw=kw):
                status,_,_=self.post(**kw)
                self.assertEqual(status,expected)
        self.assertEqual(self.calls,[])

    def test_invalid_json_or_shape(self):
        for raw in (b"not-json",b"[]",b'{"capability":"A"}'):
            with self.subTest(raw=raw):
                status,body,_=self.post(body=raw)
                self.assertEqual(status,"400 Bad Request")

    def test_factory_failure_is_unavailable_without_details(self):
        gateway=criar_gateway_hermes(
            audience=AUDIENCE,sujeitos_permitidos=frozenset({SUBJECT}),
            verificar=lambda tok,aud:CLAIMS,
            fabrica_adaptador=lambda subj: (_ for _ in ()).throw(
                RuntimeError("secret path /private/foo")))
        original=self.app
        self.app=gateway
        try:
            status,body,_=self.post()
            self.assertEqual(status,"503 Service Unavailable")
            self.assertNotIn("secret",str(body))
        finally:
            self.app=original

    def test_invalid_allowlist_fails_configuration(self):
        with self.assertRaises(ErroGateway):
            criar_gateway_hermes(
                audience=AUDIENCE,sujeitos_permitidos=frozenset(),
                fabrica_adaptador=lambda _: None,verificar=lambda *_:CLAIMS)


if __name__=="__main__":
    unittest.main()
