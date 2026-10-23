"""Valida contrato de exportação BigQuery sem rede nem dados externos."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from nivon.antt_anuario_bigquery_export import exportar
from nivon.antt_anuario_rgi import extrair_tabela_12,persistir
from test_antt_anuario_rgi import texto_base

class TestExportBigQuery(unittest.TestCase):
    def test_exportacao_16_linhas_e_proveniencia(self):
        with tempfile.TemporaryDirectory() as pasta:
            bd=Path(pasta)/"teste.sqlite"
            sha=hashlib.sha256(b"fixture").hexdigest()
            persistir(bd,extrair_tabela_12(texto_base()),sha256=sha,
                     data_coleta="2026-10-23T11:20:00Z")
            alvo=Path(pasta)/"saida.jsonl"
            estado=exportar(bd,alvo)
            self.assertEqual(estado["estado"],"JSONL_CRIADO_NAO_ENVIADO")
            rows=[json.loads(x) for x in alvo.read_text().splitlines()]
            self.assertEqual(len(rows),16)
            self.assertEqual({x["data_referencia"] for x in rows},{"2025-12-31"})
            self.assertEqual({x["escopo"] for x in rows},{"TOP_16_FLUXOS_GERAIS_ANUAIS"})
            self.assertEqual({x["sha256"] for x in rows},{sha})
            self.assertTrue(all(x["data_publicacao"] is None for x in rows))

if __name__=="__main__":
    unittest.main()
