"""Gates do crosswalk: não duplicação, direitos, escopo e proveniência."""
import copy
import unittest

from nivon.agrobr_crosswalk import ErroCrosswalk, carregar_crosswalk, reconciliar
from nivon.catalogo_fontes import carregar_catalogo


class TestAgrobrCrosswalk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = carregar_catalogo()
        cls.crosswalk = carregar_crosswalk()

    def test_reconciliacao_do_catalogo_real_sem_duplicacao(self):
        anterior = copy.deepcopy(self.catalog)
        r = reconciliar(self.catalog, self.crosswalk)
        self.assertEqual(r["fontes_agrobr_documentadas"], 41)
        self.assertEqual(r["fontes_canonicas_criadas"], 0)
        self.assertEqual(r["datasets_criados"], 0)
        self.assertEqual(self.catalog, anterior)
        self.assertEqual(sum(r["por_estado"].values()), 41)
        self.assertTrue(r["datasets_canonicos_cobertos_sem_duplicacao"] > 0)

    def test_licencas_e_coletas_nao_autorizadas(self):
        r = reconciliar(self.catalog, self.crosswalk)
        self.assertEqual(r["uso"], "NAO_COMERCIAL")
        self.assertEqual(r["coletas_ativadas"], 0)
        self.assertEqual(r["direitos_concedidos"], 0)
        for e in r["comparacoes"]:
            self.assertFalse(e["acesso_runtime_testado"])
            self.assertFalse(e["coleta_autorizada_pelo_crosswalk"])
            self.assertFalse(e["integracao_autorizada_pelo_crosswalk"])

    def test_mapeamentos_das_fontes_estrategicas(self):
        r = reconciliar(self.catalog, self.crosswalk)
        d = {x["agrobr_slug"]: x for x in r["comparacoes"]}
        self.assertEqual(d["conab"]["source_id_canonico"], "CONAB")
        self.assertEqual(d["comexstat"]["source_id_canonico"], "MDIC")
        self.assertEqual(d["cepea"]["source_id_canonico"], "CEPEA")
        self.assertEqual(d["antt_pedagio"]["source_id_canonico"], "ANTT")
        self.assertEqual(d["cepea"]["proximo_gate"], "REVISAR_DIREITOS_NAO_COMERCIAIS_POR_OPERACAO")
        self.assertEqual(d["defensivos"]["proximo_gate"], "NAO_INTEGRAR")
        # Mesmo provedor não implica dataset equivalente:
        self.assertEqual(d["antt_pedagio"]["datasets_canônicos"], [])
        self.assertEqual(d["mapa_psr"]["datasets_canônicos"], [])
        self.assertEqual(d["ana"]["datasets_canônicos"], [])
        self.assertNotIn("ANP_PPI_COMBUSTIVEIS", d["anp_diesel"]["datasets_canônicos"])
        self.assertNotIn("RADAR_AGRO", d["noticias_agricolas"]["datasets_canônicos"])

    def test_exclusao_de_receituario_e_corporate_intelligence(self):
        copy_doc = copy.deepcopy(self.crosswalk)
        next(x for x in copy_doc["entries"] if x["slug"] == "defensivos")["status"] = "NAO_MAPEADA"
        with self.assertRaises(ErroCrosswalk):
            reconciliar(self.catalog, copy_doc)

    def test_fonte_fora_do_catalogo_recusada(self):
        doc = copy.deepcopy(self.crosswalk)
        x = next(e for e in doc["entries"] if e["slug"] == "conab")
        x["source_id"] = "CONAB_FICTICIA"
        with self.assertRaises(ErroCrosswalk):
            reconciliar(self.catalog, doc)

    def test_dataset_semantico_de_outra_fonte_recusado(self):
        doc = copy.deepcopy(self.crosswalk)
        next(x for x in doc["entries"] if x["slug"] == "conab")["dataset_ids"] = ["BCB_PTAX"]
        with self.assertRaises(ErroCrosswalk):
            reconciliar(self.catalog, doc)

    def test_dataset_repetido_entre_conectores_recusado(self):
        doc = copy.deepcopy(self.crosswalk)
        next(x for x in doc["entries"] if x["slug"] == "rnc")["dataset_ids"] = ["MAPA_SANIDADE_PROTEINAS"]
        next(x for x in doc["entries"] if x["slug"] == "mapa_psr")["dataset_ids"] = ["MAPA_SANIDADE_PROTEINAS"]
        with self.assertRaises(ErroCrosswalk):
            reconciliar(self.catalog, doc)

    def test_proposito_comercial_recusado(self):
        doc = copy.deepcopy(self.crosswalk)
        doc["use_case"] = "COMMERCIAL"
        with self.assertRaises(ErroCrosswalk):
            reconciliar(self.catalog, doc)

    def test_hash_upstream_nao_pode_ser_branch_mutavel(self):
        doc = copy.deepcopy(self.crosswalk)
        doc["upstream"]["commit"] = "main"
        with self.assertRaises(ErroCrosswalk):
            reconciliar(self.catalog, doc)

    def test_entrada_duplicada_recusada(self):
        doc = copy.deepcopy(self.crosswalk)
        doc["entries"][1]["slug"] = doc["entries"][0]["slug"]
        with self.assertRaises(ErroCrosswalk):
            reconciliar(self.catalog, doc)

    def test_origem_nao_verificavel_bloqueada(self):
        doc = copy.deepcopy(self.crosswalk)
        doc["upstream"]["repository"] = "outro/agronegocio"
        with self.assertRaises(ErroCrosswalk):
            reconciliar(self.catalog, doc)

    def test_numero_de_fontes_upstream_inconsistente(self):
        doc = copy.deepcopy(self.crosswalk)
        doc["upstream"]["documented_count"] = 99
        with self.assertRaises(ErroCrosswalk):
            reconciliar(self.catalog, doc)

    def test_exclusao_sem_justificativa_recusada(self):
        doc = copy.deepcopy(self.crosswalk)
        next(e for e in doc["entries"] if e["slug"] == "defensivos").pop("motivo")
        with self.assertRaises(ErroCrosswalk):
            reconciliar(self.catalog, doc)

    def test_nao_mapeado_nao_vira_fonte_automatica(self):
        r = reconciliar(self.catalog, self.crosswalk)
        for e in r["comparacoes"]:
            if e["status"] == "NAO_MAPEADA":
                self.assertIsNone(e["source_id_canonico"])
                self.assertEqual(e["proximo_gate"], "REVISAR_RELEVANCIA_E_FONTE_CANONICA")


if __name__ == "__main__":
    unittest.main()
