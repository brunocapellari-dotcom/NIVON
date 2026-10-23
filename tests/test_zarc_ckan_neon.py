"""Contratos de persistência CKAN somente no banco agrícola Neon."""
import unittest
from nivon.zarc_ckan_neon import (
    ALLOWED_HOST,DATABASE,ErroSinalNeon,gravar_sinal_ckan
)
from nivon.zarc_sinais_ckan import normalizar_sinal,RESOURCE_ID

URL=("https://dados.agricultura.gov.br/dataset/"
     "6d3d141c-885e-41a4-ab7f-dc8ff323b96f/resource/"
     +RESOURCE_ID+"/download/dados-abertos-tabua-de-risco-safra-2026-2027.csv")


def sinal():
    return normalizar_sinal({
       "fonte_id":"MAPA_ZARC","licenca_declarada":"cc-by",
       "coleta":"2026-10-23T03:00:18.102438Z",
       "revision_id":"pkg-id","atualizado_em":"2026-10-22T07:12:04",
       "recursos":[{"id":RESOURCE_ID,"formato":"CSV",
          "url_somente_referencia":URL,"revision_id":"r-1",
          "atualizado_em":"2026-10-22T07:11:39"}]
    })


class FakeInfo:
    def __init__(self,host=ALLOWED_HOST,dbname=DATABASE):
        self.host,self.dbname=host,dbname

class Context:
    def __init__(self,obj): self.obj=obj
    def __enter__(self): return self.obj
    def __exit__(self,*args): return False

class Conn:
    def __init__(self,host=ALLOWED_HOST,dbname=DATABASE):
        self.info=FakeInfo(host,dbname)
        self.closed=False
        self.records={}
        self.queries=[]
    def transaction(self):return Context(self)
    def cursor(self):return Context(Cur(self))

class Cur:
    def __init__(self,conn):self.conn=conn;self.rowcount=0;self.latest=None
    def execute(self,sql,params):
        self.conn.queries.append(sql.strip().split()[0].upper())
        if sql.strip().startswith("INSERT"):
            k=params[1].isoformat()
            self.rowcount=0 if k in self.conn.records else 1
            if self.rowcount:
                self.conn.records[k]=params[2]
        elif "AND coletado_em<%s" in sql:
            self.latest=None
        elif sql.strip().startswith("SELECT"):
            self.latest=[self.conn.records.get(params[1].isoformat())]
    def fetchone(self):
        return self.latest

class TestNeonCkan(unittest.TestCase):
    def test_gate_off(self):
        with self.assertRaises(PermissionError):
            gravar_sinal_ckan(conn=Conn(),sinal=sinal())

    def test_banco_ptax_ou_host_externo_rejeitados(self):
        for host,db in (
            ("ep-outro.neon.tech","nivon_agro"),
            (ALLOWED_HOST,"ptax"),
            ("localhost",DATABASE),
        ):
            conn=Conn(host,db)
            with self.subTest(host=host,db=db),self.assertRaises(PermissionError):
                gravar_sinal_ckan(conn=conn,sinal=sinal(),executar=True)
            self.assertEqual(conn.queries,[])

    def test_inserir_e_repetir_observacao(self):
        conn=Conn()
        result=gravar_sinal_ckan(conn=conn,sinal=sinal(),executar=True)
        self.assertTrue(result["nova_coleta"])
        self.assertTrue(result["observacao_ckan_persistida"])
        self.assertFalse(result["dados_agricolas_inseridos"])
        self.assertFalse(result["conteudo_csv_alterado_comprovado"])
        result=gravar_sinal_ckan(conn=conn,sinal=sinal(),executar=True)
        self.assertFalse(result["nova_coleta"])
        self.assertEqual(len(conn.records),1)

    def test_mesma_coleta_com_hash_divergente_bloqueia(self):
        conn=Conn()
        a=sinal()
        gravar_sinal_ckan(conn=conn,sinal=a,executar=True)
        a["metadata_fingerprint"]="a"*64
        with self.assertRaises(ErroSinalNeon):
            gravar_sinal_ckan(conn=conn,sinal=a,executar=True)

    def test_arquivo_csv_nao_pode_entrar_como_sinal(self):
        a=sinal()
        a["versao_csv_sha256"]="1"*64
        with self.assertRaises(ErroSinalNeon):
            gravar_sinal_ckan(conn=Conn(),sinal=a,executar=True)

    def test_sinal_sem_fuso_rejeitado(self):
        a=sinal()
        a["coleta_utc"]="2026-10-23T03:00:18"
        with self.assertRaises(ErroSinalNeon):
            gravar_sinal_ckan(conn=Conn(),sinal=a,executar=True)

if __name__=="__main__":
    unittest.main()
