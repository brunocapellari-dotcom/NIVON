import json
import tempfile
import unittest
from pathlib import Path
from hashlib import sha256
from nivon.carga_bigquery_fontes import (
    planejar_carga, executar_carga, ErroCargaBigQuery
)

class BigQueryContratoTest(unittest.TestCase):
    def test_plano_sem_nuvem_ou_credencial(self):
        with tempfile.TemporaryDirectory() as p:
            path=Path(p)/"dados.jsonl"
            blob={"dataset_id":"ARG_BCRA_V1","identidade":"var1|2026-10-01",
                "fingerprint":"a"*64,"referencia":"2026-10-01",
                "competencia":None,"publicacao":None,
                "coletado_em":"2026-10-22T00:00:00+00:00",
                "unidade":None,"valor":"1234","campos":{"idVariable":1},
                "snapshot_id":"b"*64,"natureza":"INFORMADO"}
            path.write_text(json.dumps(blob)+"\n",encoding="utf-8")
            plan=planejar_carga(arquivo=path,project_id="nivon-data",dataset_id="agro")
            self.assertEqual(plan["linhas"],1)
            self.assertEqual(plan["tabela"],"nivon-data.agro.nivon_observacoes")
            self.assertEqual(plan["referencia_inicio"],"2026-10-01")
            self.assertEqual(plan["referencia_fim"],"2026-10-01")
            self.assertFalse(plan["executado"])
            with self.assertRaises(PermissionError):
                executar_carga(arquivo=path,project_id="nivon-data",dataset_id="agro")
            with self.assertRaises(ErroCargaBigQuery):
                planejar_carga(arquivo=path,project_id="x;drop",dataset_id="agro")
            path.write_text(json.dumps(blob)+"\n"+json.dumps(blob)+"\n",encoding="utf-8")
            with self.assertRaises(ErroCargaBigQuery):
                planejar_carga(arquivo=path,project_id="nivon-data",dataset_id="agro")

    def test_intervalo_particoes_min_max_sem_alargar_por_data_de_coleta(self):
        with tempfile.TemporaryDirectory() as base:
            arquivo=Path(base)/"arquivo.jsonl"
            linhas=[]
            for i,dia in enumerate(("2022-01-01","2025-06-15","2024-11-01")):
                linhas.append({
                    "dataset_id":"WORLD_BANK_AGRO_INDICADORES",
                    "identidade":f"ARG|WDI|{dia}",
                    "fingerprint":f"{i+1:064x}",
                    "referencia":dia,
                    "competencia":dia[:4],"publicacao":None,
                    "coletado_em":"2026-10-23T12:00:00+00:00",
                    "unidade":"kg/ha","valor":"5000",
                    "campos":{"fonte":"World Bank"},
                    "snapshot_id":"a"*64,"natureza":"INFORMADO"})
            arquivo.write_text("\n".join(json.dumps(x) for x in linhas)+"\n",encoding="utf-8")
            plano=planejar_carga(arquivo=arquivo,project_id="nivon-data",dataset_id="agro")
            self.assertEqual(plano["linhas"],3)
            self.assertEqual(plano["referencia_inicio"],"2022-01-01")
            self.assertEqual(plano["referencia_fim"],"2025-06-15")
            linhas[1]["referencia"]="2026-W43-5"
            arquivo.write_text("\n".join(json.dumps(x) for x in linhas)+"\n",encoding="utf-8")
            with self.assertRaises(ErroCargaBigQuery):
                planejar_carga(arquivo=arquivo,project_id="nivon-data",dataset_id="agro")

if __name__=="__main__":
    unittest.main()
