"""Testes integrados offline: parser -> HTTP autorizado -> RAW -> SQLite -> JSONL."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.coletores_dados_reais import (
    _safra_canada, _parse_ckan, _recurso_ccee, plano_series_argentina,
    parse_series_argentina, executar_coleta, ErroColetor, CANADA_CSV, CCEE_PACKAGE)
from nivon.ingestao_fontes_reais import gravar_lote, exportar_jsonl, ErroIngestao

T=datetime(2026,10,22,12,0,tzinfo=timezone.utc)
DUMMY_CSV=b"week,crop,tonnes\n2026-10-11,soybeans,100\n"

class Resp:
    status=200
    def __init__(self,url,payload,mime):
        self.url=url
        self.content=payload
        self.headers={"Content-Type":mime}
    def geturl(self):
        return self.url
    def read(self,max_bytes):
        return self.content[:max_bytes]
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False

class Fake:
    def __init__(self,mapping):
        self.mapping=mapping
        self.seen=[]
    def open(self,req,timeout=30):
        url=req.full_url
        self.seen.append(url)
        return self.mapping[url]

class DataRealTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.db=self.base/"dados.sqlite"
        self.raw=self.base/"raw"

    def test_argentina_safra_e_validacao_urls(self):
        url=plano_series_argentina(inicio="2026-10-01",fim="2026-10-02")
        self.assertIn("168.1_T_CAMBIOR_D_0_0_26",url)
        self.assertTrue(_safra_canada("2026-27").endswith("/2026-27/gsw-shg-en.csv"))
        for x in ("2025-29","2030-31","2026-2027","",None):
            with self.subTest(x=x),self.assertRaises(ErroColetor):
                _safra_canada(x)
        with self.assertRaises(ErroColetor):
            plano_series_argentina(inicio="2026-10-02",fim="2026-10-01")

    def test_argentina_parser_unidade_nao_homologada(self):
        raw=json.dumps({"data":[["2026-10-01",1500.5],["2026-10-02",None]]}).encode()
        obs=parse_series_argentina(raw)
        self.assertEqual(len(obs),1)
        self.assertTrue(obs[0]["campos"]["unidade_provisoria"])
        for invalid in ({"data":[["2026-10-01",float("nan")]]},
                        {"data":[["2026-13-01",1.0]]},
                        {"data":[["2026-10-01","1400"]]},
                        {"errors":["API indisponivel"],"data":[]}):
            with self.subTest(invalid=invalid),self.assertRaises(ErroColetor):
                parse_series_argentina(json.dumps(invalid).encode())

    def test_pipeline_argentina_idempotencia_historico_asof(self):
        url=plano_series_argentina(inicio="2026-10-01",fim="2026-10-02")
        fake=Fake({url:Resp(url,json.dumps({"data":[["2026-10-01",1400.5]]}).encode(),"application/json")})
        args={"fonte":"ARG_SERIES_CAMBIO","banco":self.db,"raw_dir":self.raw,
              "inicio":"2026-10-01","fim":"2026-10-02","executar":True,
              "cliente":fake,"instante":T}
        a=executar_coleta(**args)
        b=executar_coleta(**args)
        self.assertEqual(a["novas_observacoes"],1)
        self.assertEqual(b["novas_observacoes"],0)
        self.assertEqual(a["sha256"],b["sha256"])
        self.assertTrue(Path(a["arquivo_raw"]).is_file())
        out=exportar_jsonl(banco=self.db,destino=self.base/"staging.jsonl")
        self.assertEqual(out["observacoes"],1)
        d=json.loads((self.base/"staging.jsonl").read_text())
        self.assertEqual(d["referencia"],"2026-10-01")
        self.assertEqual(d["natureza"],"INFORMADO")
        self.assertEqual(len(fake.seen),2)
        # Nova revisao do mesmo dia deve coexistir, sem apagar a origem.
        fake.mapping[url]=Resp(url,json.dumps({"data":[["2026-10-01",1402]]}).encode(),"application/json")
        c=executar_coleta(**args)
        self.assertNotEqual(a["sha256"],c["sha256"])
        self.assertEqual(exportar_jsonl(banco=self.db,
            destino=self.base/"revisoes.jsonl")["observacoes"],2)

    def test_canada_csv_arquivo_sem_inventar_colunas(self):
        url=CANADA_CSV.format(safra="2026-27")
        fake=Fake({url:Resp(url,DUMMY_CSV,"text/csv")})
        out=executar_coleta(fonte="CAN_GRAINS_WEEKLY",banco=self.db,
            raw_dir=self.raw,safra="2026-27",executar=True,cliente=fake,instante=T)
        self.assertEqual(out["estado"],"RAW_RECEIVED")
        self.assertEqual(out["notas"]["cabecalho"],["week","crop","tonnes"])
        self.assertEqual(out["novas_observacoes"],0)

    def test_ccee_recurso_estritamente_da_fonte(self):
        recurso="123e4567-e89b-12d3-a456-426614174000"
        uri="https://dadosabertos.ccee.org.br/dataset/data/resource/"+recurso+".csv"
        meta={"success":True,"result":{"name":"pld_horario","license_id":"cc-by",
            "resources":[{"id":recurso,"format":"CSV","url":uri,"name":"PLD 2026"}]}}
        self.assertEqual(_recurso_ccee(_parse_ckan(json.dumps(meta).encode())[1],recurso),uri)
        fake=Fake({CCEE_PACKAGE:Resp(CCEE_PACKAGE,json.dumps(meta).encode(),"application/json"),
                   uri:Resp(uri,DUMMY_CSV,"text/csv")})
        out=executar_coleta(fonte="BR_CCEE_PLD",banco=self.db,
                    raw_dir=self.raw,executar=True,recurso_id=recurso,
                    cliente=fake,instante=T)
        self.assertEqual(out["estado"],"RAW_RECEIVED")
        self.assertEqual(len(fake.seen),2)
        self.assertEqual(out["notas"]["licenca"],"cc-by")
        meta["result"]["resources"][0]["url"]="http://127.0.0.1/private.csv"
        with self.assertRaises(ErroColetor):
            _recurso_ccee(_parse_ckan(json.dumps(meta).encode())[1],recurso)

    def test_default_deny_rede_sem_credencial_e_sql_injection(self):
        with self.assertRaises(PermissionError):
            executar_coleta(fonte="ARG_SERIES_CAMBIO",banco=self.db,raw_dir=self.raw)
        with self.assertRaises(ErroIngestao):
            gravar_lote(banco=self.db,diretorio_bruto=self.raw,dataset_id="x;DROP TABLE",
                        origem="https://example.org/data",raw=b"a",tipo="text/csv",coletado_em=T)
        with self.assertRaises(ErroIngestao):
            gravar_lote(banco=self.db,diretorio_bruto=self.raw,dataset_id="TEST_METRIC",
                origem="https://example.org/data",raw=b"1",tipo="application/json",
                coletado_em=T,registros=[{"identidade":"1","referencia":"2026-10-01",
                "natureza":"OBSERVADO","campos":{"v":"1"}},{"identidade":"2","referencia":"NO_DATE",
                "natureza":"OBSERVADO","campos":{"v":"2"}}])
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("select count(*) from observacoes").fetchone()[0],0)

if __name__=="__main__":
    unittest.main()
