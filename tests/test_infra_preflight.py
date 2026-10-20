"""Regressão de controles de infraestrutura: apenas fixtures em memória."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from nivon.infra_preflight import InfraError, carregar_inventario, validar_inventario


class InfraPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = carregar_inventario()

    def setUp(self):
        self.doc = copy.deepcopy(self.original)

    def test_blueprint_permite_validacao_sem_liberar_producao(self):
        result = validar_inventario(self.doc)
        self.assertEqual(result["status"], "BLUEPRINT_VALIDO_OPERACAO_BLOQUEADA")
        self.assertFalse(result["deployment_authorized"])
        self.assertEqual(result["gates_aprovados"], 0)

    def test_rejeita_ativar_prod(self):
        self.doc["environments"][2]["runtime_enabled"] = True
        with self.assertRaises(InfraError):
            validar_inventario(self.doc)

    def test_rejeita_orcamento_positivo(self):
        self.doc["deployment"]["approved_monthly_brl"] = 10
        with self.assertRaises(InfraError):
            validar_inventario(self.doc)

    def test_rejeita_cloud_verificada_sem_prova(self):
        self.doc["deployment"]["account_resources_verified"] = True
        with self.assertRaises(InfraError):
            validar_inventario(self.doc)

    def test_rejeita_publicacao_ou_live(self):
        self.doc["components"][-1]["live_enabled"] = True
        with self.assertRaises(InfraError):
            validar_inventario(self.doc)

    def test_rejeita_autorizar_gate_diretamente(self):
        self.doc["release_gates"]["BACKUP_RESTORE"] = True
        with self.assertRaises(InfraError):
            validar_inventario(self.doc)

    def test_rejeita_dependencia_ciclica(self):
        self.doc["components"][1]["depends_on"] = ["observability"]
        with self.assertRaises(InfraError):
            validar_inventario(self.doc)

    def test_rejeita_dependencia_inexistente(self):
        self.doc["components"][-1]["depends_on"] = ["componente_ficticio"]
        with self.assertRaises(InfraError):
            validar_inventario(self.doc)

    def test_rejeita_json_com_chaves_duplicadas(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "duplicado.json"
            f.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
            with self.assertRaises(InfraError):
                carregar_inventario(f)

    def test_rejeita_backup_falso(self):
        self.doc["storage_policy"]["remote_backup_verified"] = True
        with self.assertRaises(InfraError):
            validar_inventario(self.doc)


if __name__ == "__main__":
    unittest.main()
