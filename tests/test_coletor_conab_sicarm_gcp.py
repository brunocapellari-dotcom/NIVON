"""SICARM official endpoint mocked: aggregate, quarantine, idempotency, privacy."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from nivon.conab_armazens import CABECALHO_SICARM_V1
from nivon.coletor_conab_sicarm_gcp import (
    URL_OFICIAL, ErroConabRemoto, coletar_conab_armazens,
)

OPS=frozenset({"COLETA","ARMAZENAMENTO","USO_INTERNO"})
TIME=datetime(2026,10,23,15,0,0,tzinfo=timezone.utc)
EVIDENCE="Autorizacao de consulta e armazenamento de dados publicos CONAB"


def tabela(linhas=None):
    if linhas is None:
        linhas=[
            ["SINTETICO-001","A GRANEL","SILO","PRIVADO","PJ","Sorriso",
             "5107925","MT","100,50","0","0","","","EMPRESA_A","RUA_SECRETA","email@domain.local"],
            ["SINTETICO-002","A GRANEL","SILO","PRIVADO","PJ","Sorriso",
             "5107925","MT","20,50","0","0","","","EMPRESA_B","RUA_SECRETA","email2@domain.local"],
        ]
    return (";".join(CABECALHO_SICARM_V1)+"\n"+
            "\n".join(";".join(row) for row in linhas)+"\n").encode("cp1252")


class Response:
    def __init__(self,raw,*,url=URL_OFICIAL,mime="text/plain",status=200):
        self.raw=raw; self.url=url; self.status=status
        self.headers={"Content-Type":mime}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.raw[:n]


class Opener:
    def __init__(self,resp):self.resp=resp;self.calls=0
    def open(self,req,timeout):self.calls+=1;return self.resp


class TestColetorConabSicarmGCP(unittest.TestCase):
    def test_agrega_sem_identificador_pessoal_e_preserva_raw_privado(self):
        with tempfile.TemporaryDirectory() as d:
            client=Opener(Response(tabela()))
            args=dict(base=d,autorizacoes=OPS,evidencia=EVIDENCE,executar=True,
                      abridor=client,instante=TIME)
            a=coletar_conab_armazens(**args)
            b=coletar_conab_armazens(**args)
            self.assertEqual((a["municipios"],a["linhas_armazens"]),(1,2))
            self.assertEqual(a["capacidade_cadastrada_t"],121.0)
            self.assertEqual(a["novas_observacoes"],1)
            self.assertEqual(b["novas_observacoes"],0)
            self.assertEqual(a["status"],"RAW_E_AGREGADOS_EM_QUARENTENA")
            self.assertFalse(a["bigquery_canonico"])
            with sqlite3.connect(Path(d)/"fontes_reais.sqlite") as conn:
                estado=conn.execute("SELECT estado FROM snapshots").fetchone()[0]
                campos=conn.execute("SELECT campos_json FROM observacoes").fetchone()[0]
            self.assertEqual(estado,"QUARANTINED")
            self.assertNotIn("EMPRESA_A",campos)
            self.assertNotIn("RUA_SECRETA",campos)
            self.assertNotIn("email@domain.local",campos)
            self.assertIn("referencia_tecnica_da_coleta_nao_vigencia",campos)
            self.assertEqual(client.calls,2)

    def test_bloqueia_sem_autorizacao_antes_http(self):
        with tempfile.TemporaryDirectory() as d:
            client=Opener(Response(tabela()))
            with self.assertRaises(PermissionError):
                coletar_conab_armazens(base=d,abridor=client,executar=True)
            self.assertEqual(client.calls,0)

    def test_rejeita_waf_ou_layout_invalido(self):
        with tempfile.TemporaryDirectory() as d:
            for raw in (b"<html>request rejected</html>", b"not a CSV table"):
                with self.subTest(raw=raw), self.assertRaises((ErroConabRemoto,ValueError)):
                    coletar_conab_armazens(base=d,autorizacoes=OPS,evidencia=EVIDENCE,
                                           executar=True,abridor=Opener(Response(raw)),
                                           instante=TIME)
            self.assertFalse((Path(d)/"fontes_reais.sqlite").exists())

    def test_bloqueia_http_redirect_e_mime_malicioso(self):
        with tempfile.TemporaryDirectory() as d:
            for response in (
                Response(tabela(),url="https://example.com/data.txt"),
                Response(tabela(),mime="text/html")):
                with self.subTest(mime=response.headers["Content-Type"]),self.assertRaises(ErroConabRemoto):
                    coletar_conab_armazens(base=d,autorizacoes=OPS,evidencia=EVIDENCE,
                                           executar=True,abridor=Opener(response),
                                           instante=TIME)


if __name__=="__main__":
    unittest.main()
