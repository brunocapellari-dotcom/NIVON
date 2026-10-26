"""Release audit tests: no network, no credentials, no live GCP writes."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/nivon_release_readiness.py"
spec = importlib.util.spec_from_file_location("nivon_release_readiness", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

NOW = datetime(2026, 10, 25, 22, 50, tzinfo=timezone.utc)


def approved():
    return {
        "NIVON_BQ_PROJECT": "nivon-data",
        "NIVON_BQ_DATASET": "nivon_raw",
        "NIVON_GCS_BUCKET": "nivon-data-raw-2026",
        "NIVON_GCP_PROVIDER": "projects/test/locations/global/workloadIdentityPools/fixture/providers/fixture",
        "NIVON_GCP_SERVICE_ACCOUNT": "fictional@example.invalid",
        "NIVON_GCP_COST_REVIEWED": "true",
        "NIVON_PAINEL_INTERNO_WRITE_APPROVED": "true",
        "NIVON_GO_LIVE_DEPLOY_APPROVED": "true",
        "NIVON_TERMINAL_ARTIFACT_REPO": "fixture-repo",
        "NIVON_TERMINAL_EXECUTION_SA": "fixture@example.invalid",
        "NIVON_ZERO_COST_BQ_APPROVED": "true",
        "NIVON_RAW_ARCHIVE_APPROVED": "true",
        "NIVON_MARITIMO_GITHUB_SCHEDULE": "enabled",
    }


class ReleaseReadinessTests(unittest.TestCase):
    def test_real_tree_has_required_release_paths_and_safe_policies(self):
        status = mod.evaluate(ROOT, {}, now=NOW)
        self.assertEqual(status["violacoes_de_politica"], [])
        self.assertTrue(all(status["arquivos_presentes"].values()))
        self.assertEqual(status["escritas_cloud"], 0)
        self.assertEqual(status["deploys"], 0)
        self.assertFalse(status["liberacao_publica"])

    def test_no_configuration_means_no_release_authorization(self):
        result = mod.evaluate(ROOT, {}, now=NOW)
        for lane in result["trilhas"].values():
            self.assertFalse(lane["preflight_configuracao_completo"])
        self.assertTrue(result["trilhas"]["painel_interno_gcs"]["codigo_preparado"])
        self.assertFalse(result["trilhas"]["maritimo_pdf_sem_duv"]["publicacao_permitida"])

    def test_explicitly_authorized_config_is_only_ready_for_runtime_probe(self):
        result = mod.evaluate(ROOT, approved(), now=NOW)
        for item in ("painel_interno_gcs", "terminal_privado_cloud_run",
                     "maritimo_piloto_imbituba_portwatch"):
            with self.subTest(item=item):
                r = result["trilhas"][item]
                self.assertTrue(r["codigo_preparado"])
                self.assertTrue(r["preflight_configuracao_completo"])
        self.assertFalse(result["trilhas"]["terminal_privado_cloud_run"]["deploy_executado"])
        self.assertFalse(result["trilhas"]["painel_interno_gcs"]["publicacao_executada"])
        self.assertFalse(result["liberacao_publica"])

    def test_absent_cost_review_blocks_gcs_and_cloud_run(self):
        flags = approved()
        flags.pop("NIVON_GCP_COST_REVIEWED")
        r = mod.evaluate(ROOT, flags, now=NOW)
        self.assertFalse(r["trilhas"]["painel_interno_gcs"]["preflight_configuracao_completo"])
        self.assertFalse(r["trilhas"]["terminal_privado_cloud_run"]["preflight_configuracao_completo"])

    def test_absent_raw_archival_right_blocks_maritime_ingestion(self):
        flags = approved()
        flags.pop("NIVON_RAW_ARCHIVE_APPROVED")
        r = mod.evaluate(ROOT, flags, now=NOW)
        self.assertFalse(r["trilhas"]["maritimo_piloto_imbituba_portwatch"]["preflight_configuracao_completo"])
        self.assertTrue(r["trilhas"]["painel_interno_gcs"]["preflight_configuracao_completo"])

    def test_gcp_project_or_dataset_drift_blocks_all_main_lanes(self):
        flags = approved()
        flags["NIVON_BQ_DATASET"] = "unknown"
        r = mod.evaluate(ROOT, flags, now=NOW)
        self.assertTrue(all(
            not r["trilhas"][key]["preflight_configuracao_completo"]
            for key in ("painel_interno_gcs", "terminal_privado_cloud_run",
                        "maritimo_piloto_imbituba_portwatch")
        ))

    def test_unapproved_workflow_change_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for files in mod.ARTIFACTS.values():
                for name in files:
                    dest = base / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    source = ROOT / name
                    dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            maritime = base / ".github/workflows/maritimo-gcp-primeiro-lote.yml"
            maritime.write_text(
                maritime.read_text(encoding="utf-8").replace(
                    "vars.NIVON_MARITIMO_GITHUB_SCHEDULE == 'enabled'",
                    "vars.NIVON_MARITIMO_GITHUB_SCHEDULE != 'disabled'"
                ), encoding="utf-8"
            )
            r = mod.evaluate(base, approved(), now=NOW)
            self.assertIn("maritimo_cron_somente_ativacao_afirmativa", r["violacoes_de_politica"])
            self.assertFalse(r["trilhas"]["maritimo_piloto_imbituba_portwatch"]["codigo_preparado"])

    def test_cli_strict_runs_offline_and_does_not_open_gcp(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--strict-policy"],
            capture_output=True, text=True, timeout=25, cwd=str(ROOT)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["tipo"], "AUDITORIA_ESTÁTICA_OFFLINE_SEM_CLOUD")
        self.assertEqual(record["consultas_bigquery"], 0)
        self.assertEqual(record["fontes_homologadas_por_este_comando"], 0)

    def test_json_report_is_immutable_new_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "status.json"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--json", str(target)],
                capture_output=True, text=True, timeout=25, cwd=str(ROOT)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            first = target.read_bytes()
            replay = subprocess.run(
                [sys.executable, str(SCRIPT), "--json", str(target)],
                capture_output=True, text=True, timeout=25, cwd=str(ROOT)
            )
            self.assertNotEqual(replay.returncode, 0)
            self.assertEqual(target.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
