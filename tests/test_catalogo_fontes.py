import copy
import unittest

from nivon.catalogo_fontes import (
    ErroCatalogo, GRUPOS, PRODUTOS_ESTRATEGICOS, carregar_catalogo,
    diagnostico, proximo_gate, validar_catalogo,
)


class TestCatalogoMestre(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogo = carregar_catalogo()

    def test_fonte_canonica_sem_colisao(self):
        meta = validar_catalogo(self.catalogo)
        self.assertGreaterEqual(meta["fontes"], 50)
        self.assertGreaterEqual(meta["datasets"], 75)
        self.assertEqual(meta["coletas_ativadas"], 0)

    def test_todos_dominios_e_commodities_presentes(self):
        grupos = {d["group"] for d in self.catalogo["datasets"]}
        produtos = {p for d in self.catalogo["datasets"] for p in d["products"]}
        self.assertTrue(GRUPOS <= grupos)
        self.assertTrue(PRODUTOS_ESTRATEGICOS <= produtos)

    def test_dez_portos_brasileiros_distintos(self):
        ports = [d for d in self.catalogo["datasets"] if d["id"].startswith("LINEUP_")]
        self.assertEqual(len(ports), 10)
        self.assertTrue(all(d["group"] == "PORTOS" for d in ports))
        self.assertFalse(any(d["enabled"] for d in ports))

    def test_restritos_nao_sao_agendados(self):
        r = diagnostico(self.catalogo, grupo="PRECOS")
        self.assertEqual(r["prontos_para_agendar"], 0)
        self.assertEqual(r["bloqueados_ate_gates"], r["total"])
        self.assertTrue(any(x["next_gate"].startswith("DIREITOS_COMERCIAIS")
                            for x in r["datasets"]))

    def test_filtro_por_commodity_diesel(self):
        r = diagnostico(self.catalogo, produto="DIESEL")
        self.assertGreater(r["total"], 10)
        self.assertTrue(any(x["id"] == "ANP_PRECO_REVENDA_DIESEL" for x in r["datasets"]))

    def test_filtro_prioridade_p0(self):
        r = diagnostico(self.catalogo, prioridade="P0")
        self.assertTrue(r["total"] >= 10)
        self.assertTrue(all(x["priority"] == "P0" for x in r["datasets"]))

    def test_comex_nao_une_municipio_sh4_a_ncm(self):
        ncm = next(d for d in self.catalogo["datasets"] if d["id"] == "MDIC_COMEX_NCM")
        mun = next(d for d in self.catalogo["datasets"] if d["id"] == "MDIC_COMEX_MUNICIPIO_SH4")
        self.assertIn("sem_municipio", ncm["topic"])
        self.assertIn("sem_ncm", mun["topic"])

    def test_bloqueio_se_ativar_coleta_sem_gate(self):
        doc = copy.deepcopy(self.catalogo)
        doc["datasets"][0]["enabled"] = True
        with self.assertRaises(ErroCatalogo):
            validar_catalogo(doc)

    def test_bloqueio_se_ativar_republicacao(self):
        doc = copy.deepcopy(self.catalogo)
        doc["datasets"][0]["commercial_redistribution_authorized"] = True
        with self.assertRaises(ErroCatalogo):
            validar_catalogo(doc)

    def test_bloqueio_em_dataset_sem_contrato_temporal(self):
        doc = copy.deepcopy(self.catalogo)
        doc["datasets"][0]["data_dates_required"] = ["competencia", "coleta"]
        with self.assertRaises(ErroCatalogo):
            validar_catalogo(doc)

    def test_bloqueio_fonte_inexistente(self):
        doc = copy.deepcopy(self.catalogo)
        doc["datasets"][0]["source_id"] = "FONTE_FALSA"
        with self.assertRaises(ErroCatalogo):
            validar_catalogo(doc)

    def test_bloqueio_ids_repetidos(self):
        doc = copy.deepcopy(self.catalogo)
        doc["datasets"].append(copy.deepcopy(doc["datasets"][0]))
        with self.assertRaises(ErroCatalogo):
            validar_catalogo(doc)

    def test_rejeitar_url_fonte_insegura(self):
        doc = copy.deepcopy(self.catalogo)
        doc["sources"][0]["official_url"] = "http://127.0.0.1/"
        with self.assertRaises(ErroCatalogo):
            validar_catalogo(doc)

    def test_prioridade_e_estagio_nao_equivalem_homologacao(self):
        d = next(d for d in self.catalogo["datasets"] if d["id"] == "CONAB_GRAOS_SERIES")
        self.assertEqual(d["stage"], "REAL_SNAPSHOT_TESTED")
        self.assertFalse(d["enabled"])
        self.assertIn("HISTORICO_PERSISTENTE", proximo_gate(d, self.catalogo))

    def test_proibido_ausencia_commodity(self):
        doc = copy.deepcopy(self.catalogo)
        for d in doc["datasets"]:
            d["products"] = [x for x in d["products"] if x != "SORGO"]
        with self.assertRaises(ErroCatalogo):
            validar_catalogo(doc)

    def test_fonte_whatsapp_separada_do_gov(self):
        dado = next(d for d in self.catalogo["datasets"] if d["id"] == "FRETES_WHATSAPP_AUTORIZADO")
        self.assertEqual(dado["source_id"], "WHATSAPP_AI")
        self.assertFalse(dado["enabled"])


if __name__ == "__main__":
    unittest.main()
