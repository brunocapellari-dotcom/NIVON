"""Catálogo de adoção GitHub da infraestrutura: segurança e anti-tool-sprawl."""
import json
import unittest
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"config"/"infra_ferramentas_github.v1.json"
DECISIONS={"ADOPT","BENCHMARK","RESERVE","REJECT"}
PRIORITIES={"P0","P1","P2"}


class TestInfraFerramentasGitHub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc=json.loads(PATH.read_text(encoding="utf-8"))

    def test_catalogo_sem_ativacao(self):
        d=self.doc
        self.assertEqual(d["schema"],"nivon.infrastructure.github_tools.v1")
        self.assertEqual(d["status"],"RESEARCHED_NOT_INSTALLED")
        self.assertFalse(d["policy"]["paid_auto_fallback"])
        self.assertFalse(d["policy"]["deploy_allowed"])
        self.assertFalse(d["policy"]["clone_or_copy_repo_automatically"])
        self.assertFalse(d["policy"]["install_automatically"])

    def test_ferramentas_identificadas_e_auditaveis(self):
        records=self.doc["tools"]
        self.assertGreaterEqual(len(records),8)
        ids=[x["id"] for x in records]
        urls=[x["repository"] for x in records]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(urls),len(set(urls)))
        for tool in records:
            self.assertIn(tool["decision"], DECISIONS)
            self.assertIn(tool["priority"], PRIORITIES)
            self.assertTrue(tool["repository"].startswith("https://github.com/"))
            self.assertTrue(tool["license_url"].startswith(tool["repository"]+"/blob/"))
            self.assertTrue(tool["license_verified_from_repo"])
            self.assertFalse(tool["installed_by_this_pr"])
            self.assertFalse(tool["runtime_enabled"])
            self.assertTrue(tool["needs_transitive_license_review"])
            for k in ("purpose","integration","gate"):
                self.assertGreater(len(tool[k]),10)

    def test_selecao_nao_requer_kubernetes_ou_gpu(self):
        ids={x["id"] for x in self.doc["tools"] if x["decision"]=="ADOPT"}
        self.assertIn("restic",ids)
        self.assertIn("docker-compose",ids)
        self.assertIn("gitleaks",ids)
        self.assertIn("trivy",ids)
        self.assertNotIn("kubernetes",ids)
        self.assertNotIn("neuralforecast",ids)

    def test_backup_continuo_nao_instalado_diretamente(self):
        by_id={x["id"]:x for x in self.doc["tools"]}
        self.assertEqual(by_id["litestream"]["decision"],"BENCHMARK")
        self.assertEqual(by_id["otel-collector"]["decision"],"RESERVE")
        self.assertEqual(by_id["caddy"]["decision"],"RESERVE")


if __name__=="__main__":
    unittest.main()
