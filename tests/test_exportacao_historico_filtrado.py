"""Recorte de histórico por competência e referência antes de BigQuery."""
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone

from nivon.ingestao_fontes_reais import gravar_lote, exportar_jsonl, ErroIngestao


class HistoricoJsonlTest(unittest.TestCase):
    def test_filtrar_ano_e_safra_sem_perda(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)
            db=base/"banco.sqlite"
            for ano,comp in ((2024,"2024-2025"),(2025,"2025-2026")):
                gravar_lote(banco=db,diretorio_bruto=base/"raw",
                    dataset_id="CAN_GRAINS_CROP_YEAR_WEEKLY",
                    origem=f"https://grainscanada.gc.ca/test/{ano}.csv",
                    raw=f"arquivo {ano}".encode(),tipo="text/csv",
                    coletado_em=datetime(2026,10,23,tzinfo=timezone.utc),
                    estado="NORMALIZED",registros=[{
                        "identidade":f"{ano}|soybeans|Western",
                        "referencia":f"{ano}-10-01",
                        "competencia":comp,
                        "valor":"1250","unidade":"t","natureza":"INFORMADO",
                        "campos":{"grain":"soybeans","tonnes":"1250"}}])
            tudo=exportar_jsonl(banco=db,destino=base/"tudo.jsonl")
            self.assertEqual(tudo["observacoes"],2)
            por_comp=exportar_jsonl(banco=db,destino=base/"comp.jsonl",
                dataset_id="CAN_GRAINS_CROP_YEAR_WEEKLY",
                competencia="2024-2025")
            self.assertEqual(por_comp["observacoes"],1)
            por_data=exportar_jsonl(banco=db,destino=base/"ano.jsonl",
                dataset_id="CAN_GRAINS_CROP_YEAR_WEEKLY",
                referencia_inicio="2025-01-01",referencia_fim="2025-12-31")
            self.assertEqual(por_data["observacoes"],1)
            row=json.loads((base/"ano.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["referencia"],"2025-10-01")
            with self.assertRaises(ErroIngestao):
                exportar_jsonl(banco=db,destino=base/"inv.jsonl",
                    referencia_inicio="2026-01-01",referencia_fim="2024-01-01")

if __name__=="__main__":
    unittest.main()
