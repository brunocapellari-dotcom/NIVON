"""Auditoria de metadados GCP sem rede: os contratos são integrais."""
import unittest
from types import SimpleNamespace
from nivon.auditoria_gcp_readonly import (
    auditar, avaliar_metadados, ErroAuditoriaCloud,
    ESQUEMA_CANONICO, ESQUEMA_AGRO,
    REQUIRED_CANONICO, REQUIRED_AGRO, CLUSTER_CANONICO, CLUSTER_AGRO,
)

def tabela_campos(campos, particao, cluster, obrigatorios):
    return SimpleNamespace(
        schema=[SimpleNamespace(name=n,field_type=t,
                   mode="REQUIRED" if n in obrigatorios else "NULLABLE")
                for n,t in campos.items()],
        time_partitioning=SimpleNamespace(field=particao),
        clustering_fields=list(cluster), require_partition_filter=True)


class AuditoriaNivonTest(unittest.TestCase):
    def _avaliar(self,**alteracoes):
        params=dict(projeto="nivon-data",dataset="nivon_raw",
            bucket="nivon-data-raw-2026",
            local_dataset="southamerica-east1",local_bucket="SOUTHAMERICA-EAST1",
            tabela_canonica=tabela_campos(ESQUEMA_CANONICO,"data_referencia",
                CLUSTER_CANONICO,REQUIRED_CANONICO),
            tabela_agro=tabela_campos(ESQUEMA_AGRO,"data_coleta",
                CLUSTER_AGRO,REQUIRED_AGRO))
        return avaliar_metadados(**(params|alteracoes))

    def test_metadados_integrais_sem_alterar_cloud(self):
        r=self._avaliar()
        self.assertTrue(r["acesso_metadados_confirmado"])
        self.assertTrue(r["regiao_conforme"])
        self.assertTrue(all(x["schema_conforme"] and x["particao_conforme"]
            and x["cluster_conforme"] and x["filtro_particao_obrigatorio"]
            for x in r["tabelas"]))
        self.assertEqual(r["gravacoes"],0)
        self.assertEqual(r["consultas_sql"],0)
        self.assertFalse(r["pronto_para_operacao"])
        self.assertEqual(ESQUEMA_CANONICO["campos"],"JSON")
        self.assertEqual(ESQUEMA_AGRO["origem_url"],"STRING")

    def test_tabela_ausente_e_schema_incorreto_diagnosticados(self):
        r=self._avaliar(tabela_canonica=None,
            tabela_agro=tabela_campos({"data_coleta":"STRING"},"referencia",
                CLUSTER_AGRO,REQUIRED_AGRO))
        self.assertFalse(r["tabelas"][0]["existe"])
        self.assertFalse(r["tabelas"][1]["schema_conforme"])
        self.assertFalse(r["tabelas"][1]["particao_conforme"])
        erros=r["tabelas"][1]["colunas_pendentes_ou_incorretas"]
        for nome in ("data_coleta","data_referencia","snapshot_id",
                     "origem_url","campos"):
            self.assertIn(nome,erros)
        self.assertFalse(r["pronto_para_operacao"])

    def test_campos_omissos_modo_trocado_ou_cluster_errado_bloqueados(self):
        good=tabela_campos(ESQUEMA_CANONICO,"data_referencia",
                          CLUSTER_CANONICO,REQUIRED_CANONICO)
        good.clustering_fields=["dataset_id","identidade","snapshot_id"]
        r=self._avaliar(tabela_canonica=good)
        self.assertTrue(r["tabelas"][0]["schema_conforme"])
        self.assertFalse(r["tabelas"][0]["cluster_conforme"])
        good.clustering_fields=list(CLUSTER_CANONICO)
        good.require_partition_filter=False
        r=self._avaliar(tabela_canonica=good)
        self.assertFalse(r["tabelas"][0]["particao_conforme"])
        self.assertFalse(r["tabelas"][0]["filtro_particao_obrigatorio"])
        good.require_partition_filter=True
        campo=next(f for f in good.schema if f.name=="data_referencia")
        campo.mode="NULLABLE"  # canônico exige data_referencia REQUIRED
        r=self._avaliar(tabela_canonica=good)
        self.assertFalse(r["tabelas"][0]["schema_conforme"])
        self.assertIn("data_referencia",r["tabelas"][0]["colunas_pendentes_ou_incorretas"])
        staged=tabela_campos(ESQUEMA_AGRO,"data_coleta",
                             CLUSTER_AGRO,REQUIRED_AGRO)
        next(f for f in staged.schema if f.name=="data_referencia").mode="REQUIRED"
        r=self._avaliar(tabela_agro=staged)
        self.assertFalse(r["tabelas"][1]["schema_conforme"])

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
