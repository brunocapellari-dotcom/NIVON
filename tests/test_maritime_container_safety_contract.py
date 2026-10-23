"""Offline-only static guards. These do NOT replace a real Docker build/test."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DockerIsolationContractTests(unittest.TestCase):
    def test_docker_wrapper_retains_no_network_no_privileges_readonly(self):
        text = (ROOT / "scripts/run_maritime_pdf_container.sh").read_text()
        for requirement in (
            "--network none", "--read-only", "--cap-drop ALL",
            "--security-opt no-new-privileges:true",
            "--pids-limit 40", "--memory 1536m", "--cpus 1.5",
            "--pull never", "type=bind,source=", "target=/inputs,readonly",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, text)

    def test_container_image_is_nonroot_with_only_offline_cli(self):
        image = (ROOT / "docker/Dockerfile.maritime-pdf-offline").read_text()
        self.assertIn("USER 65532:65532", image)
        self.assertIn("ENTRYPOINT", image)
        self.assertIn("scripts/maritime_pdf_batch.py", image)
        self.assertNotIn("EXPOSE ", image)
        self.assertNotIn("API_KEY", image)
        self.assertNotIn("CMD [\"cron", image)

    def test_no_automatic_pull_or_live_service_activation(self):
        wrapper = (ROOT / "scripts/run_maritime_pdf_container.sh").read_text()
        self.assertNotIn("docker pull ", wrapper)
        self.assertNotIn("--network host", wrapper)
        self.assertNotIn("--privileged", wrapper)
        self.assertNotIn("curl ", wrapper)
        self.assertIn("if [[", wrapper)


if __name__ == "__main__":
    unittest.main()
