"""PTAX incremental BigQuery: plano offline, proveniencia e bloqueio de custo."""
import json,os,stat,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scripts.ptax_neon_to_bigquery_jsonl import normalize
from scripts.ptax_bigquery_incremental import planejar,executar,CargaBloqueada

def row(idx:int, curr="USD"):
    return normalize({"id":idx,"currency":curr,"reference_date":"2026-10-22",
     "quote_time_original":f"2026-10-22 13:12:{idx:02d}.300403",
     "bulletin_type":"COTACAO_DOLAR_DIARIA" if curr=="USD" else "Abertura",
     "buy_brl":"5.037700000","sell_brl":"5.038300000","unit":"BRL/"+curr,
     "source":"Banco Central do Brasil / PTAX","license":"ODbL",
     "published_at":None,"first_collected_at":"2026-10-23T01:30:03.289850Z",
     "last_verified_at":"2026-10-23T01:30:03.289850Z",
     "observation_kind":"INFORMADO"})

def write(path,rows):
    with path.open("w",encoding="utf8") as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False)+"\n")
    path.chmod(0o600)

class PTAXBigQueryGate(unittest.TestCase):
    def test_validar_lote_e_contagens(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"ptax.jsonl"
            write(p,[row(1),row(2,"EUR")])
            plan=planejar(p)
            self.assertEqual(plan["rows"],2)
            self.assertEqual(plan["count_by_currency"],{"USD":1,"EUR":1})
            self.assertFalse(plan["bigquery_executed"])
            self.assertFalse(plan["cutover_approved"])
    def test_rejeita_corrupcao_de_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.jsonl"
            a=row(1);a["buy_brl"]="9.111"
            write(p,[a])
            with self.assertRaises(CargaBloqueada):planejar(p)
    def test_rejeita_duplicacao_quote(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.jsonl";r=row(1);write(p,[r,r])
            with self.assertRaises(CargaBloqueada):planejar(p)
    def test_rejeita_ids_nao_ordenados(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.jsonl";write(p,[row(2),row(1)])
            with self.assertRaises(CargaBloqueada):planejar(p)
    def test_rejeita_permissoes_publicas(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.jsonl";write(p,[row(1)]);p.chmod(0o644)
            with self.assertRaises(CargaBloqueada):planejar(p)
    def test_sem_aprovacao_nao_importa_sdk_nem_toca_gcp(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.jsonl";write(p,[row(1)])
            with patch.dict(os.environ,{"NIVON_GCP_WRITE_APPROVED":"false","NIVON_GCP_COST_REVIEWED":"false"}):
                with self.assertRaises(PermissionError):
                    executar(p,approve=True)
                with self.assertRaises(PermissionError):
                    executar(p,approve=False)
    def test_sem_referencia_publicacao_nao_inferir(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.jsonl";write(p,[row(1)])
            r=json.loads(p.read_text().splitlines()[0])
            self.assertIsNone(r["published_at"])
            self.assertIsNone(r["origem_sha256"])
            self.assertEqual(planejar(p)["status"],"VALIDATED_PRIVATE_BATCH_NOT_LOADED")

if __name__=="__main__":unittest.main()
