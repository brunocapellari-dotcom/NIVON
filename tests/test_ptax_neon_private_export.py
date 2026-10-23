"""PTAX Neon OIDC bridge — contratos sintéticos, nenhuma rede ou GCP."""
import json
import tempfile
from pathlib import Path
import unittest
from scripts.ptax_neon_private_export import (
    PrivateExportError,validated_endpoint,row_to_normalized,stream_pages,export,
)
URL="https://br-twilight-cell-b77ukd6x-ptaxbridge.compute.c-13.us-east-1.aws.neon.tech"
def record(id="1", currency="USD",val="5.123400000",date="2026-10-22"):
    return {"id":id,"currency":currency,"reference_date":date,
       "quote_time_original":date+" 13:12:09.300403",
       "bulletin_type":"COTACAO_DOLAR_DIARIA" if currency=="USD" else "Abertura",
       "buy_brl":val,"sell_brl":"5.123500000","unit":"BRL/"+currency,
       "source":"Banco Central do Brasil / PTAX","license":"ODbL",
       "published_at":None,"first_collected_at":"2026-10-23T01:30:03.289850Z",
       "last_verified_at":"2026-10-23T01:30:03.289850Z",
       "observation_kind":"INFORMADO"}

def stub(upper="3",rows=None):
    rows=rows if rows is not None else [record("1"),record("3",currency="EUR")]
    def f(endpoint,token,path,query):
        if path=="/checkpoint":
            return {"status":"CHECKPOINT","upper_id":upper,"row_count":len(rows)}
        assert path=="/export"
        after=int(query["after"])
        vals=[x for x in rows if after<int(x["id"])<=int(query["upto"])]
        return {"status":"OK","upper_id":query["upto"],"after_id":str(after),
          "rows":vals,"received":len(vals),
          "next_after_id":vals[-1]["id"] if vals else str(after),
          "has_more":False}
    return f

class ExportBridge(unittest.TestCase):
    def test_endpoint_restrito(self):
        self.assertEqual(validated_endpoint(URL),URL)
        for u in ("http://"+URL[8:],
                  "https://example.com","https://ptaxbridge.evil.com",
                  URL+"?token=leak"):
            with self.subTest(u=u),self.assertRaises(PrivateExportError):
                validated_endpoint(u)
    def test_conversao_decimal_e_timezone(self):
        src,r=row_to_normalized(record())
        self.assertEqual(src["id"],1)
        self.assertEqual(r["buy_brl"],"5.1234")
        self.assertEqual(r["published_at"],None)
        self.assertEqual(r["quality_status"],"NEON_EXPORT_UNVERIFIED")
        self.assertIsNone(r["origem_sha256"])
    def test_snapshot_paginado_e_checkpoint(self):
        up,rows,count=stream_pages(URL,"jwt",0,api=stub())
        self.assertEqual(up,3)
        self.assertEqual([x["id"] for x in rows],["1","3"])
        self.assertEqual(count,2)
    def test_export_realiza_escrita_privada_sem_gcp(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);s=base/"source.jsonl"; t=base/"bq.jsonl"
            r=export(URL,s,t,api=stub(),token="jwt")
            self.assertEqual(r["exported"],2)
            self.assertFalse(r["gcp_loaded"])
            self.assertEqual(len(s.read_text().splitlines()),2)
            self.assertEqual(len(t.read_text().splitlines()),2)
            self.assertEqual({x["currency"] for x in map(json.loads,t.read_text().splitlines())},{"USD","EUR"})
            self.assertEqual(t.stat().st_mode & 0o777,0o600)
            with self.assertRaises(PrivateExportError):
                export(URL,s,t,api=stub(),token="jwt")
    def test_referencias_iguais_nao_misturam_moedas(self):
        a=row_to_normalized(record("1"))[1]
        b=row_to_normalized(record("2",currency="EUR"))[1]
        self.assertNotEqual(a["quote_id"],b["quote_id"])
    def test_data_sem_fuso_bloqueada(self):
        bad=record()
        bad["first_collected_at"]="2026-10-22T12:00:00"
        with self.assertRaises(PrivateExportError):
            row_to_normalized(bad)
    def test_cursor_deve_avancar_estritamente(self):
        rows=[record("1"),record("1")]
        with self.assertRaises(PrivateExportError):
            stream_pages(URL,"jwt",0,api=stub(upper="2",rows=rows))
    def test_falha_na_segunda_linha_remove_arquivos(self):
        bad=record("2")
        bad["license"]=""
        with tempfile.TemporaryDirectory() as tmp:
            s,t=Path(tmp)/"source.jsonl",Path(tmp)/"target.jsonl"
            with self.assertRaises(PrivateExportError):
                export(URL,s,t,api=stub(upper="2",rows=[record("1"),bad]),token="jwt")
            self.assertFalse(s.exists())
            self.assertFalse(t.exists())
    def test_incremental_after_id(self):
        r=record("3")
        upper,rows,n=stream_pages(URL,"jwt",2,api=stub(upper="3",rows=[r]))
        self.assertEqual([x["id"] for x in rows],["3"])
    def test_snapshot_vazio_nao_e_carga(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PrivateExportError):
                export(URL,Path(tmp)/"a.jsonl",Path(tmp)/"b.jsonl",
                       api=stub(upper="0",rows=[]),token="jwt")
if __name__=="__main__":unittest.main()
