"""Auditoria de metadados GCP sem rede, sem criação de recursos."""
import unittest
from types import SimpleNamespace
from nivon.auditoria_gcp_readonly import auditar, avaliar_metadados, ErroAuditoriaCloud

def tabela_campos(campos,particao):
    return SimpleNamespace(
        schema=[SimpleNamespace(name=n,field_type=t) for n,t in campos.items()],
        time_partitioning=SimpleNamespace(field=particao))

CANON={
 "dataset_id":"STRING","identidade":"STRING","fingerprint":"STRING",
 "data_referencia":"DATE","data_coleta":"TIMESTAMP",
 "data_publicacao":"TIMESTAMP","snapshot_id":"STRING","natureza":"STRING",
}
AGRO={"data_coleta":"TIMESTAMP","data_referencia":"DATE","snapshot_id":"STRING"}

class AuditoriaNivonTest(unittest.TestCase):
    def _avaliar(self,**alteracoes):
        params=dict(projeto="nivon-data",dataset="nivon_raw",
            bucket="nivon-data-raw-2026",
            local_dataset="southamerica-east1",local_bucket="SOUTHAMERICA-EAST1",
            tabela_canonica=tabela_campos(CANON,"data_referencia"),
            tabela_agro=tabela_campos(AGRO,"data_coleta"))
        return avaliar_metadados(**(params|alteracoes))

    def test_metadados_sem_alterar_cloud(self):
        r=self._avaliar()
        self.assertTrue(r["acesso_metadados_confirmado"])
        self.assertTrue(r["regiao_conforme"])
        self.assertTrue(all(x["schema_conforme"] and x["particao_conforme"]
            for x in r["tabelas"]))
        self.assertEqual(r["gravacoes"],0)
        self.assertEqual(r["consultas_sql"],0)
        self.assertFalse(r["pronto_para_operacao"])

    def test_tabela_ausente_e_schema_incorreto_sao_diagnosticados(self):
        r=self._avaliar(tabela_canonica=None,
            tabela_agro=tabela_campos({"data_coleta":"STRING"},"referencia"))
        self.assertFalse(r["tabelas"][0]["existe"])
        self.assertFalse(r["tabelas"][1]["schema_conforme"])
        self.assertFalse(r["tabelas"][1]["particao_conforme"])
        self.assertEqual(r["tabelas"][1]["colunas_pendentes_ou_incorretas"],
            ["data_coleta","data_referencia","snapshot_id"])
        self.assertFalse(r["pronto_para_operacao"])

    def test_regiao_e_config_estritos(self):
        r=self._avaliar(local_bucket="us-east1")
        self.assertFalse(r["regiao_conforme"])
        with self.assertRaises(ErroAuditoriaCloud):
            self._avaliar(local_dataset=None)
        with self.assertRaises(ValueError):
            auditar(projeto="not.valid",dataset="nivon_raw",
                bucket="nivon-data-raw-2026")

    def test_planejamento_nao_abre_credenciais(self):
        result=auditar(projeto="nivon-data",dataset="nivon_raw",
                      bucket="nivon-data-raw-2026")
        self.assertEqual(result["tipo"],"PLANO_SEM_REDE")
        self.assertFalse(result["executado"])

if __name__=="__main__":
    unittest.main()
