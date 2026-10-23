"""Gates da nuvem e relatorios de coletores sem credenciais externas."""
import json
import tempfile
import unittest
from pathlib import Path

from nivon.preflight_gcp_fontes import validar_config, CANONICOS, STAGE
from nivon.carga_bigquery_fontes import ErroCargaBigQuery

class CloudConfigTest(unittest.TestCase):
    def test_particao_e_schema_canonico(self):
        self.assertIn(("data_referencia","DATE"),CANONICOS)
        self.assertIn(("data_coleta","TIMESTAMP"),CANONICOS)
        self.assertIn(("data_publicacao","TIMESTAMP"),CANONICOS)
        self.assertIn(("campos","JSON"),STAGE)
        obj=validar_config(projeto="nivon-data",dataset="agro",
                           bucket="nivon-raw-archive")
        self.assertEqual(obj["tabela"],"nivon-data.agro.nivon_observacoes")

    def test_identificadores_arbitrarios_bloqueados(self):
        for params in (
            dict(projeto="a",dataset="agro",bucket="nivon-raw-archive"),
            dict(projeto="nivon-data",dataset="a;DROP TABLE",bucket="nivon-raw-archive"),
            dict(projeto="nivon-data",dataset="agro",bucket="127.0.0.1/bad"),
        ):
            with self.subTest(params=params),self.assertRaises(ValueError):
                validar_config(**params)

class LoteTest(unittest.TestCase):
    def test_relatorio_parcial_nao_passar_verde(self):
        # O script esta em scripts/, nao no pacote nivon.
        import importlib.util
        script=Path(__file__).resolve().parents[1]/"scripts"/"verificar_status_fontes.py"
        spec=importlib.util.spec_from_file_location("verificar_status_fontes",script)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"report.json"
            doc={"sucesso":1,"falhas":1,
                 "fontes":[{"fonte":"BCRA","estado":"COLETADO"},
                           {"fonte":"CCEE","estado":"FALHOU"}]}
            path.write_text(json.dumps(doc),encoding="utf-8")
            self.assertFalse(module.verificar_lote(path)["aprovado"])
            doc={"sucesso":2,"falhas":0,
                 "fontes":[{"fonte":"BCRA","estado":"COLETADO"},
                           {"fonte":"CCEE","estado":"COLETADO"}]}
            path.write_text(json.dumps(doc),encoding="utf-8")
            self.assertTrue(module.verificar_lote(path)["aprovado"])
            doc["sucesso"]=1
            path.write_text(json.dumps(doc),encoding="utf-8")
            with self.assertRaises(ValueError):
                module.verificar_lote(path)

if __name__=="__main__":
    unittest.main()
