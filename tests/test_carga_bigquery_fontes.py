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
            self.assertFalse(plan["executado"])
            with self.assertRaises(PermissionError):
                executar_carga(arquivo=path,project_id="nivon-data",dataset_id="agro")
            with self.assertRaises(ErroCargaBigQuery):
                planejar_carga(arquivo=path,project_id="x;drop",dataset_id="agro")
            path.write_text(json.dumps(blob)+"\n"+json.dumps(blob)+"\n",encoding="utf-8")
            with self.assertRaises(ErroCargaBigQuery):
                planejar_carga(arquivo=path,project_id="nivon-data",dataset_id="agro")

if __name__=="__main__":
    unittest.main()
