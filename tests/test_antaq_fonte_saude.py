import json
import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError

from nivon.antaq_fonte_saude import (
    OFFICIAL_PAGE, OFFICIAL_ZIP, OFFICIAL_NOTICE, SECONDARY_API,
    KNOWN_SECONDARY, monitorar, sondar,
)


class Resp:
    def __init__(self, status, typ, body):
        self.status=status
        self.headers={"Content-Type":typ}
        self.body=body
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,n): return self.body[:n]


class Transporte:
    def __init__(self, mapa):
        self.mapa=mapa
        self.calls=[]
    def open(self,req,timeout):
        self.calls.append((req.full_url,req.get_method()))
        spec=self.mapa[(req.full_url,req.get_method())]
        if isinstance(spec,Exception): raise spec
        return Resp(*spec)


class TestFonte(unittest.TestCase):
    def test_nao_homologa_por_status_http(self):
        c=Transporte({
            (OFFICIAL_PAGE,"GET"):(200,"text/html",b"Estatistico Aquaviario em manutencao"),
            (OFFICIAL_ZIP,"HEAD"):(200,"application/zip",b""),
            (OFFICIAL_NOTICE,"HEAD"):(200,"text/html",b""),
            (SECONDARY_API,"GET"):(200,"application/json",
                json.dumps({"sha":KNOWN_SECONDARY}).encode()),
        })
        doc=monitorar(transport=c,relogio=datetime(2026,10,23,tzinfo=timezone.utc))
        self.assertEqual(len(c.calls),4)
        self.assertEqual(doc["sinais"][1]["estado"],"CANDIDATO_A_DOWNLOAD_OFICIAL")
        self.assertEqual(doc["sinais"][3]["estado"],"REPLICA_SEM_REVISAO")
        self.assertEqual(doc["decisao"],"NENHUMA_FONTE_E_HOMOLOGADA_POR_STATUS_HTTP")

    def test_acesso_bloqueado_e_nova_revisao_requer_auditoria(self):
        blocked=HTTPError(OFFICIAL_PAGE,403,"Forbidden",{},None)
        c=Transporte({
            (OFFICIAL_PAGE,"GET"):blocked,
            (SECONDARY_API,"GET"):(200,"application/json",
               json.dumps({"sha":"1"*40}).encode()),
        })
        self.assertEqual(sondar(OFFICIAL_PAGE,transport=c)["estado"],"ACESSO_BLOQUEADO")
        self.assertEqual(sondar(SECONDARY_API,transport=c)["estado"],"REPLICA_NOVA_REVISAO_AVALIAR")
        self.assertEqual(len(c.calls),2)

    def test_redirecionamento_para_aviso_institucional(self):
        redirect = HTTPError(OFFICIAL_ZIP,301,"Moved",
                             {"Location":OFFICIAL_NOTICE},None)
        c=Transporte({(OFFICIAL_ZIP,"HEAD"):redirect})
        self.assertEqual(sondar(OFFICIAL_ZIP,metodo="HEAD",
                              transport=c)["estado"],
                         "REDIRECIONAMENTO_PARA_AVISO_OFICIAL")
        self.assertEqual(len(c.calls),1)

    def test_url_fora_lista_nega_antes_da_rede(self):
        with self.assertRaises(ValueError):
            sondar("https://example.com/private",transport=object())
        with self.assertRaises(ValueError):
            sondar(SECONDARY_API,metodo="POST",transport=object())


if __name__=="__main__":
    unittest.main()
