"""Host preflight does not call real Claude, Codex, Docker or networks in CI."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nivon import preparacao_host


class TestPreflightHost(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src/nivon").mkdir(parents=True)
        (self.root / "tests").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_sandbox_is_readonly_offline_and_explicit_no_pull(self):
        args = preparacao_host.sandbox_arguments(self.root, image="nivon-agentes:test-py311")
        self.assertEqual(args[0:2], ["docker", "run"])
        self.assertIn("--network", args)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertEqual(args[args.index("--pull") + 1], "never")
        self.assertIn("--read-only", args)
        self.assertTrue(any("dst=/workspace,readonly" in arg for arg in args))
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", args)
        self.assertEqual(args[-1], "nivon-agentes:test-py311")

    def test_unknown_image_cannot_be_executed(self):
        with self.assertRaises(ValueError):
            preparacao_host.sandbox_arguments(self.root, image="untrusted/repo:latest")

    def test_full_test_suite_ok_and_no_models_launched(self):
        def fake(args, **kwargs):
            if "unittest" in args:
                return subprocess.CompletedProcess(args, 0, "", "Ran 640 tests in 7.3s\nOK\n")
            return subprocess.CompletedProcess(args, 0, '{"passed":true}', "")
        with patch.object(preparacao_host.subprocess, "run", side_effect=fake) as calls:
            result = preparacao_host.smoke(root=self.root, image="nivon-agentes:test-py311")
        self.assertTrue(result["ready"])
        self.assertEqual(result["tests"], 640)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(calls.call_count, 2)
        self.assertTrue(all(call.args[0][0] == "docker" for call in calls.call_args_list))

    def test_skips_are_not_marked_fully_ready(self):
        def fake(args, **kwargs):
            if "unittest" in args:
                return subprocess.CompletedProcess(args, 0, "", "Ran 640 tests\nOK (skipped=2)")
            return subprocess.CompletedProcess(args, 0, "ok", "")
        with patch.object(preparacao_host.subprocess, "run", side_effect=fake):
            result = preparacao_host.smoke(root=self.root, image="python:3.11-slim")
        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "optional_tests_skipped")
        with patch.object(preparacao_host.subprocess, "run", side_effect=fake):
            tolerated = preparacao_host.smoke(root=self.root, allow_skips=True)
        self.assertTrue(tolerated["ready"])

    def test_failed_test_refuses_pilot(self):
        with patch.object(preparacao_host.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 1, "", "Traceback assertion FAILED")):
            state = preparacao_host.smoke(root=self.root)
        self.assertFalse(state["ready"])
        self.assertEqual(state["reason"], "test_failure")

    def test_auth_gates_do_not_run_suite(self):
        doctor = {"supported_host": True, "authentication": {"claude": "unknown",
                  "codex": "subscription"}, "docker_image_local": True,
                  "ready_for_pilot": False}
        with patch.object(preparacao_host, "doctor", return_value=doctor), \
             patch.object(preparacao_host, "smoke") as smoke:
            result = preparacao_host.readiness(root=self.root)
        self.assertFalse(result["ready_for_night_pilot"])
        smoke.assert_not_called()
        self.assertIn("Confirmar login", " ".join(result["actions"]))

    def test_readiness_passes_explicit_image_to_doctor(self):
        doctor = {"supported_host": True, "authentication": {"claude": "subscription",
                  "codex": "subscription"}, "docker_image_local": True,
                  "ready_for_pilot": True}
        with patch.object(preparacao_host, "doctor", return_value=doctor) as checked, \
             patch.object(preparacao_host, "smoke", return_value={"ready": True, "tests": 640}) as verify:
            result = preparacao_host.readiness(root=self.root, image="nivon-agentes:test-py311")
        checked.assert_called_once_with(image="nivon-agentes:test-py311")
        verify.assert_called_once_with(root=self.root, image="nivon-agentes:test-py311", allow_skips=False)
        self.assertTrue(result["ready_for_night_pilot"])


if __name__ == "__main__":
    unittest.main()
