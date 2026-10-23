"""Gate do carregador real: não aceitar acesso remoto nem executar por padrão."""
import unittest
from nivon.zarc_pg_loader_teste import carregar_teste,ErroCargaZarc

class FakeInfo:
    def __init__(self,host):self.host=host
class FakeConn:
    def __init__(self,host,autocommit=False,closed=False):
        self.info=FakeInfo(host)
        self.autocommit=autocommit
        self.closed=closed

class TestPgTestGate(unittest.TestCase):
    def test_opt_in_obrigatorio(self):
        with self.assertRaises(PermissionError):
            carregar_teste(sqlite=None,raiz_raw=None,sha256="a"*64,postgres=None)
    def test_proibe_host_externo_mesmo_opt_in(self):
        for host in ("neon.tech","ep-example.neon.tech","10.1.1.1","example.com",None):
            with self.subTest(host=host),self.assertRaises(PermissionError):
                carregar_teste(sqlite=None,raiz_raw=None,sha256="a"*64,
                              postgres=FakeConn(host),executar=True)
    def test_autocommit_ou_conexao_fechada(self):
        with self.assertRaises(ErroCargaZarc):
            carregar_teste(sqlite=None,raiz_raw=None,sha256="a"*64,
                 postgres=FakeConn("127.0.0.1",autocommit=True),executar=True)
        with self.assertRaises(ErroCargaZarc):
            carregar_teste(sqlite=None,raiz_raw=None,sha256="a"*64,
                 postgres=FakeConn("localhost",closed=True),executar=True)
    def test_limite_lotes(self):
        for limit in (0,501,True,"500"):
            with self.subTest(limit=limit),self.assertRaises(ErroCargaZarc):
                carregar_teste(sqlite=None,raiz_raw=None,sha256="a"*64,
                    postgres=FakeConn("127.0.0.1"),executar=True,tamanho_lote=limit)

if __name__=="__main__":
    unittest.main()
