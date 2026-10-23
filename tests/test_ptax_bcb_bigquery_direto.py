"""PTAX BCB directo: contrato primario, fonte oficial e bloqueio cloud."""
from datetime import datetime,timezone
from decimal import Decimal
import json
import tempfile
from pathlib import Path
import os
import unittest
from unittest.mock import patch
from scripts.ptax_bcb_bigquery_direto import (
    coletar,url_bcb,salvar,load_gcp,FonteBCPBloqueada
)

class Response:
    status=200
    def __init__(self,uri,data):
        self.uri=uri
        self.data=json.dumps(data).encode()
    def geturl(self):return self.uri
    def read(self,n):return self.data[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False

class PTAXDireta(unittest.TestCase):
    def test_links_oficiais_ambas_moedas(self):
        self.assertIn("CotacaoDolarPeriodo",url_bcb("USD","2026-10-20","2026-10-23"))
        self.assertIn("CotacaoMoedaPeriodo",url_bcb("EUR","2026-10-20","2026-10-23"))
        self.assertIn("%27EUR%27",url_bcb("EUR","2026-10-20","2026-10-23"))
    def test_mapeamento_sem_neon_ou_data_publicacao_falsa(self):
        def open_req(req,timeout):
            data={"value":[{"dataHoraCotacao":"2026-10-22 13:12:09.000",
              "cotacaoCompra":5.100001,"cotacaoVenda":5.100002}]}
            return Response(req.full_url,data)
        rows=coletar("USD","2026-10-20","2026-10-23",opener=open_req,
                    agora=datetime(2026,10,23,12,0,tzinfo=timezone.utc))
        self.assertEqual(len(rows),1)
        r=rows[0]
        self.assertEqual(r["currency"],"USD")
        self.assertEqual(r["reference_date"],"2026-10-22")
        self.assertIsNone(r["published_at"])
        self.assertIsNone(r["source_neon_row_id"])
        self.assertEqual(r["quality_status"],"BCB_PRIMARIO_INFORMADO")
        self.assertEqual(r["buy_brl"],"5.100001")
        self.assertEqual(r["quote_time_original"],"2026-10-22 13:12:09.000")
    def test_erro_paginacao_odata(self):
        def op(req,timeout):
            return Response(req.full_url,{"value":[],"@odata.nextLink":"https://elsewhere"})
        with self.assertRaises(FonteBCPBloqueada):
            coletar("USD","2026-10-20","2026-10-23",opener=op)
    def test_erro_redirect(self):
        def op(req,timeout):
            return Response("https://untrusted.com",{"value":[]})
        with self.assertRaises(FonteBCPBloqueada):
            coletar("USD","2026-10-20","2026-10-23",opener=op)
    def test_erro_janela_desconhecida(self):
        with self.assertRaises(FonteBCPBloqueada):
            url_bcb("BRL","2026-10-20","2026-10-23")
    def test_arquivo_privado_e_nenhuma_escrita(self):
        def op(req,timeout):
            return Response(req.full_url,{"value":[{
              "dataHoraCotacao":"2026-10-22 13:12:09",
              "cotacaoCompra":5.11,"cotacaoVenda":5.12}]})
        rec=coletar("USD","2026-10-20","2026-10-23",opener=op)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bcb.jsonl"
            stats=salvar(rec,p)
            self.assertFalse(stats["bigquery_loaded"])
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            with patch.dict(os.environ,{"NIVON_GCP_WRITE_APPROVED":"false","NIVON_GCP_COST_REVIEWED":"false"}):
                with self.assertRaises(PermissionError):load_gcp(p)
            with self.assertRaises(FonteBCPBloqueada):salvar(rec,p)

if __name__=="__main__":unittest.main()
