"""QA do catálogo: QCL usa ZIP real; nenhum status é promovido a produção."""
import unittest
from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas


class TestQCLAtualizado(unittest.TestCase):
    def test_rota_conectada_ao_zip_valido_sem_cron(self):
        cat=carregar_catalogo()
        rot=carregar_rotas()
        self.assertEqual(validar_catalogo(cat)["coletas_ativadas"],0)
        self.assertEqual(validar_rotas(rot,cat)["coletas_ativadas"],0)
        d=next(x for x in cat["datasets"] if x["id"]=="FAO_FAOSTAT_LONG_RUN")
        r=next(x for x in rot["entries"] if x["dataset_id"]=="FAO_FAOSTAT_LONG_RUN")
        self.assertEqual(d["existing_module"],"nivon.faostat_qcl_stream.executar_qcl")
        self.assertEqual(r["locator"]["kind"],"DIRECT_PUBLIC_FILE")
        self.assertTrue(r["locator"]["url"].endswith("Production_Crops_Livestock_E_All_Data_(Normalized).zip"))
        self.assertIn("REAL_HTTP_2026_10_21",r["implementation_scope"])
        self.assertFalse(d["enabled"])
        self.assertFalse(r["runtime_enabled"])
        self.assertFalse(r["scheduled_enabled"])
        self.assertIsNone(r["last_verified_data"])
        self.assertIn("BIGQUERY_PERSISTENCE_INTEGRATION",r["gates_missing"])

    def test_catalogo_manifest_permanece_separado(self):
        cat=carregar_catalogo()
        d=next(x for x in cat["datasets"] if x["id"]=="FAO_FAOSTAT_BULK_CATALOGO")
        self.assertEqual(d["existing_module"],"nivon.faostat_bulk_manifest.consultar_manifest")
        self.assertNotEqual(d["id"],"FAO_FAOSTAT_LONG_RUN")


if __name__=="__main__":
    unittest.main()
