"""Integração PR #8 em PR #30: contratos e bloqueios antes da publicação."""
import unittest
from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas
from nivon.lineup_nacional import carregar_escopo
from nivon.briefing_diario import gerar_texto
from nivon.coleta_web import FonteWeb


class TestIntegracaoPR8(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogo = carregar_catalogo()
        cls.rotas = carregar_rotas()
        cls.escopo = carregar_escopo()

    def test_preserva_quatro_datasets_historicos_e_cobertura_nacional(self):
        c = validar_catalogo(self.catalogo)
        self.assertEqual(len(self.catalogo["sources"]), 101)
        self.assertEqual(len(self.catalogo["datasets"]), 139)
        self.assertEqual(len(self.escopo["ports"]), 45)
        ids = {x["id"] for x in self.catalogo["datasets"]}
        self.assertTrue({"NOAA_ENSO_RONI", "CFTC_COT_WEEKLY",
                         "USDA_WASDE_RELEASE_VINTAGES", "FAO_FAOSTAT_LONG_RUN"} <= ids)
        self.assertEqual(validar_rotas(self.rotas, self.catalogo)["rotas"], 139)

    def test_nenhum_catalogo_atribuido_como_coleta_ou_lineup_ativo(self):
        self.assertTrue(all(not x["enabled"] and not x["collection_authorized"]
                            and not x["commercial_redistribution_authorized"]
                            for x in self.catalogo["datasets"]))
        self.assertTrue(all(not x["runtime_enabled"] and not x["scheduled_enabled"]
                            for x in self.rotas["entries"]))
        self.assertTrue(all(not x["live_enabled"] and not x["parser_homologated"]
                            and not x["endpoint_verified"]
                            for x in self.escopo["ports"]))

    def test_candidatos_portuarios_nao_sao_feeds_homologados(self):
        portos = {x["id"]: x for x in self.escopo["ports"]}
        for ident in ("ITAQUI", "SANTAREM", "BARCARENA_VILA_DO_CONDE"):
            porto = portos[ident]
            self.assertFalse(porto["endpoint_verified"])
            self.assertFalse(porto["live_enabled"])

    def test_edicao_canonica_nao_insere_secao_de_impactos(self):
        fontes = {"TESTE": {"status_direitos": "APROVADA",
                            "operacoes": ["LEITURA", "RESUMO", "PUBLICACAO_DERIVADA"]}}
        noticia = {"fonte_id": "TESTE", "fonte": "Fonte Sintética",
                   "titulo": "Safra e mercado em análise", "categoria": "SAFRA E PRODUÇÃO",
                   "resumo": "Observação de teste autorizada.",
                   "url": "https://exemplo.org/noticia/2026",
                   "publicado_em": "2026-10-21T07:00:00-04:00",
                   "impacto_brasil": "Não exibir avaliação adicional"}
        texto, recusas = gerar_texto([noticia], fontes,
            gerado_em="2026-10-21T07:30:00-04:00")
        self.assertEqual(recusas, [])
        self.assertIn("RESUMO ESTRATÉGICO DO AGRONEGÓCIO", texto)
        self.assertNotIn("Possível impacto", texto)
        self.assertNotIn("Não exibir avaliação adicional", texto)

    def test_xml_fora_de_operacao_permanece_bloqueado(self):
        fonte = FonteWeb(fonte_id="TESTE", url="https://exemplo.org/rss",
                         dominio_autorizado="exemplo.org", formato="XML")
        with self.assertRaises(PermissionError):
            fonte.verificar()


if __name__ == "__main__":
    unittest.main()
