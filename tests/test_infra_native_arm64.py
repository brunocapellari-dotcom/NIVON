"""Contrato de CI NATIVO ARM64, separado de experimento AMD64."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/infra_native_arm64.yml"


class TestNativeARM64(unittest.TestCase):
    def setUp(self):
        self.raw = WF.read_text(encoding="utf-8")

    def test_label_runner_publico_e_fail_closed(self):
        self.assertIn("runs-on: ubuntu-24.04-arm", self.raw)
        self.assertIn("if: github.event.repository.private == false", self.raw)
        self.assertIn("NIVON_NATIVE_ARM64_RUNNER_AND_DOCKER_OK", self.raw)
        self.assertIn('machine not in ("aarch64", "arm64")', self.raw)
        self.assertIn('["docker","info","--format","{{.Architecture}}"]', self.raw)

    def test_base_digest_identico_and_both_images_native(self):
        baseline = (ROOT / "infra/docker/Dockerfile.worker").read_text(encoding="utf-8")
        candidate = (ROOT / "infra/docker/Dockerfile.worker-trim").read_text(encoding="utf-8")
        from_line = re.search(r"^FROM .+$", baseline, flags=re.MULTILINE).group(0)
        self.assertIn(from_line, candidate)
        self.assertIn(from_line.removeprefix("FROM "), self.raw)
        self.assertIn("docker pull --platform linux/arm64", self.raw)
        self.assertIn("docker build --network=none --platform linux/arm64", self.raw)
        self.assertIn("Dockerfile.worker-trim", self.raw)
        self.assertIn('test "$arch" = "arm64"', self.raw)
        self.assertNotIn("pip uninstall", baseline)

    def test_execucao_isolada_sem_segredos_ou_runtime_real(self):
        for item in (
            "--platform linux/arm64", "--network none", "--read-only",
            "--cap-drop ALL", "no-new-privileges:true", "--user 65532:65532",
            "--mode self-check", "--mode synthetic-once",
            "NIVON_OFFLINE_STATE_DIR=", "sudo chmod 0700",
            "NATIVE_ARM64_RUNTIME_AND_TRIM_OK",
        ):
            with self.subTest(item=item):
                self.assertIn(item, self.raw)
        for forbidden in ("docker push", "docker login", "deploy:",
                          "secrets.", "upload-artifact@", "pull_request_target:",
                          "schedule:", "privileged", "continue-on-error: true"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.raw)

    def test_scanner_arm64_fixo_e_sbom_sem_upload(self):
        self.assertIn("trivy_0.76.0_Linux-ARM64.tar.gz", self.raw)
        self.assertIn("aab21e677a7b7071fc79f1711480840754c18a1b9d9cefa7ccd06af63a0e8f4c", self.raw)
        self.assertIn("sha256sum -c", self.raw)
        self.assertIn("--format cyclonedx", self.raw)
        self.assertIn("nivon-arm64-sbom.json", self.raw)
        self.assertIn("nivon.infra_trim_compare", self.raw)
        self.assertIn("SEM AUTORIZACAO DE RELEASE", self.raw)

    def test_actions_pinned_permissions_read_and_no_deploy(self):
        self.assertIn("permissions:\n  contents: read", self.raw)
        self.assertRegex(self.raw, r"actions/checkout@[0-9a-f]{40}")
        self.assertRegex(self.raw, r"actions/setup-python@[0-9a-f]{40}")
        self.assertIn("persist-credentials: false", self.raw)
        self.assertIn("timeout-minutes: 19", self.raw)
        self.assertIn("cancel-in-progress: true", self.raw)


if __name__ == "__main__":
    unittest.main()
