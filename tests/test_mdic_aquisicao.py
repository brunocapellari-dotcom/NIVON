import hashlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from nivon.mdic_manifesto import INDEX
from nivon.mdic_aquisicao import baixar_csv_anual_mdic,ErroDownloadMDIC

URL="https://balanca.mdic.gov.br/balanca/bd/comexstat-bd/ncm/EXP_2026.csv"
ITEM={"ano":2026,"direcao":"EXPORTACAO","granularidade":"NCM",
      "url":URL,"fonte":"MDIC_COMEX_STAT_DADOS_ABERTOS",
      "estado":"LINK_OFICIAL_DESCOBERTO_SEM_DOWNLOAD"}
MAN={"fonte":INDEX,"sha256_html":"a"*64,"arquivos":[ITEM]}
OFF={"datasets":[{"id":"MDIC_COMEX_NCM","source_id":"MDIC",
                   "enabled":False,"collection_authorized":False}]}
ON={"datasets":[{"id":"MDIC_COMEX_NCM","source_id":"MDIC",
                  "enabled":True,"collection_authorized":True}]}
PAYLOAD=b"CO_ANO;CO_MES;CO_NCM\n2026;10;12019000\n"
class Response:
    status=200
    def __init__(self,url,payload=PAYLOAD,mime="text/csv",length=None,status=200):
        self.url=url;self.payload=io.BytesIO(payload)
        self.headers={"Content-Type":mime}
        if length is not None:self.headers["Content-Length"]=str(length)
        self.status=status
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.payload.read(n)
class Opener:
    def __init__(self,**kw):self.kw=kw;self.calls=0
    def open(self,req,timeout):
        self.calls+=1
        return Response(URL,**self.kw)
class TestAquisiçãoMDIC(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir=Path(tmp.name)
        os.chmod(self.dir,0o700)
    def obter(self,**kw):
        return baixar_csv_anual_mdic(manifesto=MAN,item=ITEM,
            catalogo=kw.pop("catalogo",ON),
            diretorio_privado=self.dir,
            direitos=kw.pop("direitos",frozenset({"COLETA","ARMAZENAMENTO"})),
            evidencia_direitos=kw.pop("evidencia_direitos","DOC-TESTE-2026"),
            permitir_rede=kw.pop("permitir_rede",True),**kw)
    def test_off_bloqueia_antes_do_abridor(self):
        opener=Opener()
        with self.assertRaises(PermissionError):
            self.obter(catalogo=OFF,abridor=opener)
        self.assertEqual(opener.calls,0)
    def test_sem_optin_expresso_bloqueia_rede(self):
        op=Opener()
        with self.assertRaises(PermissionError):
            self.obter(permitir_rede=False,abridor=op)
        self.assertEqual(op.calls,0)
    def test_direitos_insuficientes_impedem_rede(self):
        op=Opener()
        with self.assertRaises(PermissionError):
            self.obter(direitos=frozenset({"COLETA"}),abridor=op)
        self.assertEqual(op.calls,0)
    def test_manifesto_forjado_ou_url_fora_bloqueados(self):
        op=Opener()
        with self.assertRaises(ErroDownloadMDIC):
            baixar_csv_anual_mdic(manifesto={**MAN,"arquivos":[]},
                item=ITEM,catalogo=ON,diretorio_privado=self.dir,
                permitir_rede=True,abridor=op)
        bad={**ITEM,"url":"https://evil.example/EXP_2026.csv"}
        with self.assertRaises(ErroDownloadMDIC):
            baixar_csv_anual_mdic(manifesto={**MAN,"arquivos":[bad]},
                item=bad,catalogo=ON,diretorio_privado=self.dir,
                permitir_rede=True,abridor=op)
        self.assertEqual(op.calls,0)
    def test_csv_integridade_vintage_privado_e_idempotencia(self):
        op=Opener()
        a=self.obter(abridor=op)
        self.assertEqual(a["sha256"],hashlib.sha256(PAYLOAD).hexdigest())
        path=Path(a["arquivo_local"])
        self.assertEqual(path.read_bytes(),PAYLOAD)
        self.assertTrue(path.exists())
        self.assertEqual(path.name,"EXP_2026.csv")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
        b=self.obter(abridor=op)
        self.assertEqual(a["arquivo_local"],b["arquivo_local"])
        self.assertEqual(op.calls,2)
    def test_waf_html_rejeitado_e_temporario_removido(self):
        with self.assertRaises(ErroDownloadMDIC):
            self.obter(abridor=Opener(payload=b"<html>Access Denied</html>",mime="text/csv"))
        self.assertEqual(list(self.dir.iterdir()),[])
    def test_truncamento_detectado_e_removido(self):
        with self.assertRaises(ErroDownloadMDIC):
            self.obter(abridor=Opener(length=100))
        self.assertEqual(list(self.dir.iterdir()),[])
    def test_limite_bytes_impede_dump_grande(self):
        with self.assertRaises(ErroDownloadMDIC):
            self.obter(abridor=Opener(),limite_bytes=10)
    def test_status_ou_mime_incorreto(self):
        with self.assertRaises(ErroDownloadMDIC):
            self.obter(abridor=Opener(status=206))
        with self.assertRaises(ErroDownloadMDIC):
            self.obter(abridor=Opener(mime="text/html"))
    def test_diretorio_publico_rejeitado(self):
        os.chmod(self.dir,0o755)
        with self.assertRaises(PermissionError):
            self.obter(abridor=Opener())
    def test_versao_local_corrompida_nao_substituida(self):
        op=Opener()
        r=self.obter(abridor=op)
        path=Path(r["arquivo_local"])
        path.write_bytes(b"CORROMPIDO"+b"x"*(len(PAYLOAD)-9))
        with self.assertRaises(ErroDownloadMDIC):
            self.obter(abridor=op)
        self.assertIn(b"CORROMPIDO",path.read_bytes())
