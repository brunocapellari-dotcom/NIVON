"""Escopo por serviço não concede permissão a outros datasets da instituição."""
import copy
import contextlib
import io
import json
import unittest

from nivon.catalogo_fontes import carregar_catalogo
from nivon.rotas_coleta import carregar_rotas
from nivon.escopo_acessos_privados import ErroEscopoAcesso, auditar_escopo, main


class TestEscopoAcessosPrivados(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogo = carregar_catalogo()
        cls.rotas = carregar_rotas()

    def test_conciliacao_real_documental_sem_mutacoes(self):
        before_cat = copy.deepcopy(self.catalogo)
        before_rotas = copy.deepcopy(self.rotas)
        result = auditar_escopo(self.catalogo, self.rotas)
        self.assertEqual(result["servicos_auditados"], 3)
        self.assertEqual(result["autenticados"], 0)
        self.assertEqual(result["habilitados"], 0)
        self.assertEqual(before_cat, self.catalogo)
        self.assertEqual(before_rotas, self.rotas)

    def test_usda_fas_nao_valida_usda_nass_wasde_ou_export_sails(self):
        report = auditar_escopo(self.catalogo, self.rotas)
        usda = next(x for x in report["resumo"] if x["fonte_id"] == "USDA")
        self.assertEqual(usda["dataset_canonico_potencial"], "USDA_PSD")
        self.assertEqual(set(
            usda["outros_datasets_nao_habilitados_pela_credencial"]
        ), {"USDA_NASS", "USDA_WASDE_RELEASE_VINTAGES", "USDA_EXPORT_SALES"})
        self.assertFalse(usda["autenticacao_real_verificada"])
        self.assertFalse(usda["habilitar_coleta"])

    def test_inmet_bdmep_nao_autoriza_api_horaria_continua(self):
        report = auditar_escopo(self.catalogo, self.rotas)
        inmet = next(x for x in report["resumo"] if x["fonte_id"] == "INMET")
        self.assertIn("ARQUIVO_HISTORICO", inmet["escopo_tecnico"])
        self.assertIn("NAO_API_CONTINUA", inmet["escopo_tecnico"])
        self.assertFalse(inmet["api_ou_link_continuo_homologado"])

    def test_ana_telemetria_adotada_nao_equivale_rede_toda(self):
        report = auditar_escopo(self.catalogo, self.rotas)
        ana = next(x for x in report["resumo"] if x["fonte_id"] == "ANA")
        self.assertEqual(ana["servico"], "ANA_HIDROWEB_TELEMETRIA_ADOTADA")
        self.assertFalse(ana["amostra_real_verificada"])

    def test_dados_nao_publicaveis_e_sem_direitos_verificados(self):
        report = auditar_escopo(self.catalogo, self.rotas)
        for x in report["resumo"]:
            self.assertFalse(x["publicavel"])
            self.assertFalse(x["direitos_por_operacao_verificados"])
            self.assertFalse(x["habilitar_coleta"])
            self.assertFalse(x["ingestao_historica_verificada"])

    def test_dataset_alvo_removido_e_bloqueado(self):
        catalog = copy.deepcopy(self.catalogo)
        catalog["datasets"] = [d for d in catalog["datasets"] if d["id"] != "USDA_PSD"]
        with self.assertRaises((ValueError, ErroEscopoAcesso)):
            auditar_escopo(catalog, self.rotas)

    def test_rota_excluida_bloqueada(self):
        rotas = copy.deepcopy(self.rotas)
        rotas["entries"] = [x for x in rotas["entries"] if x["dataset_id"] != "ANA_HIDRO"]
        with self.assertRaises((ValueError, ErroEscopoAcesso)):
            auditar_escopo(self.catalogo, rotas)

    def test_nao_promove_outros_datasets_usda(self):
        catalog = copy.deepcopy(self.catalogo)
        item = next(x for x in catalog["datasets"] if x["id"] == "USDA_NASS")
        item["enabled"] = True
        with self.assertRaises((ValueError, ErroEscopoAcesso)):
            auditar_escopo(catalog, self.rotas)

    def test_cli_resumo_sem_segredos_ou_endpoints_credenciados(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--resumo"])
        self.assertEqual(code, 0)
        out = json.loads(buffer.getvalue())
        self.assertEqual(out["estado"], "ESCOPO_DOCUMENTAL_SEM_AUTENTICACAO")
        self.assertNotIn("resumo", out)
        self.assertNotIn("senha", json.dumps(out).lower())
        self.assertEqual(out["habilitados"], 0)


if __name__ == "__main__":
    unittest.main()
