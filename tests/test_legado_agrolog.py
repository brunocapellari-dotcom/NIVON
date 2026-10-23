"""Regressoes de integridade para migracao de fontes AgroLog -> NIVON."""
import copy
import unittest
from pathlib import Path

from nivon.legado_agrolog import (
    ALIAS_PROVEDORES, ErroLegado, LINKS, NIVON, REGISTRO,
    _ler_json, executar, gerar_relatorio, validar_snapshots,
)


class TestMigracaoLegadoAgrolog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registro = _ler_json(REGISTRO)
        cls.links = _ler_json(LINKS)
        cls.nivon = _ler_json(NIVON)

    def test_snapshot_real_provado_e_inerte(self):
        self.assertEqual(len(self.registro["sources"]), 68)
        self.assertGreaterEqual(len(self.links["links"]), 560)
        self.assertFalse(self.registro["migration_policy"]["enabled"])
        self.assertFalse(self.registro["migration_policy"]["rights_inherited"])
        self.assertFalse(self.links["collection_enabled"])
        self.assertEqual(len(set(x["url"] for x in self.links["links"])), len(self.links["links"]))

    def test_conciliacao_de_provedores_criticos(self):
        relatorio = gerar_relatorio(self.registro, self.links, self.nivon)
        por_id = {x["fonte_legada"]: x for x in relatorio["conciliacao"]}
        self.assertEqual(por_id["conab_armazens_cadastrados"]["fonte_nivon"], "CONAB")
        self.assertEqual(por_id["imea_operational_xlsx"]["fonte_nivon"], "IMEA")
        self.assertEqual(por_id["antt_mdfe_public"]["fonte_nivon"], "ANTT")
        self.assertIn("CONAB_ARMAZENS_CAPACIDADE", por_id["conab_armazens_cadastrados"]["datasets_nivon"])
        self.assertEqual(por_id["sema_mt_sisflora"]["proxima_acao"], "CADASTRAR_OU_MAPEAR_PROVEDOR")
        self.assertIsNone(por_id["official_port_lineups"]["fonte_nivon"])

    def test_reusa_codigo_como_candidato_nao_como_homologado(self):
        relatorio = executar()
        self.assertEqual(relatorio["resumo"]["coletores_habilitados_pela_migracao"], 0)
        self.assertTrue(all(not x["coleta_habilitada"] and not x["direitos_herdados"]
                            and x["estado_nivon"] == "REFERENCIA_NAO_HOMOLOGADA"
                            for x in relatorio["conciliacao"]))

    def test_nao_altera_catalogo_nivon(self):
        catalogo = copy.deepcopy(self.nivon)
        antes = copy.deepcopy(catalogo)
        gerar_relatorio(self.registro, self.links, catalogo)
        self.assertEqual(catalogo, antes)

    def test_classes_heterogeneas_preservadas(self):
        relatorio = executar(so_resumo=True)
        self.assertGreater(relatorio["resumo"]["urls_por_classe"]["dados"], 100)
        self.assertGreater(relatorio["resumo"]["urls_por_classe"]["radar"], 60)
        self.assertGreater(relatorio["resumo"]["urls_por_classe"]["conhecimento"], 100)
        self.assertNotIn("conciliacao", relatorio)

    def test_bloqueia_execucao_legada_ou_direitos_implicitos(self):
        for key in ("enabled", "scheduled", "rights_inherited"):
            registro = copy.deepcopy(self.registro)
            registro["migration_policy"][key] = True
            with self.subTest(key=key), self.assertRaises(ErroLegado):
                validar_snapshots(registro, self.links, self.nivon)

    def test_bloqueia_links_ativados_e_urls_invalidas(self):
        links = copy.deepcopy(self.links)
        links["collection_enabled"] = True
        with self.assertRaises(ErroLegado):
            validar_snapshots(self.registro, links, self.nivon)
        links = copy.deepcopy(self.links)
        links["links"][0]["url"] = "file:///etc/passwd"
        with self.assertRaises(ErroLegado):
            validar_snapshots(self.registro, links, self.nivon)

    def test_bloqueia_alias_falso(self):
        self.assertIn("CONAB", {x["id"] for x in self.nivon["sources"]})
        self.assertTrue(ALIAS_PROVEDORES)
        cat = copy.deepcopy(self.nivon)
        cat["sources"] = [x for x in cat["sources"] if x["id"] != "CONAB"]
        with self.assertRaises(ErroLegado):
            validar_snapshots(self.registro, self.links, cat)

    def test_bloqueia_colisao_ids_e_documentos_corrompidos(self):
        registro = copy.deepcopy(self.registro)
        registro["sources"].append(copy.deepcopy(registro["sources"][0]))
        with self.assertRaises(ErroLegado):
            validar_snapshots(registro, self.links, self.nivon)
        links = copy.deepcopy(self.links)
        links["links"].append(copy.deepcopy(links["links"][0]))
        with self.assertRaises(ErroLegado):
            validar_snapshots(self.registro, links, self.nivon)

    def test_upstream_fixado_e_proveniencia(self):
        origem = self.registro["upstream"]
        self.assertEqual(origem["repository"], "brunocapellari-dotcom/AgroLogMT")
        self.assertEqual(len(origem["ref"]), 40)
        self.assertEqual(len(origem["blob_sha"]), 40)
        self.assertEqual(self.links["origin"]["spreadsheet_id"],
                         "18n1LWLZ6Fi3iSTbo7HgdgwhuHKZZ1TshrVnz4HEFWiU")


if __name__ == "__main__":
    unittest.main()
