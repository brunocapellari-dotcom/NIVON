"""Ferramentas: inspeção segura sem invocar provedores."""
import subprocess
import unittest
from unittest.mock import patch

from nivon import ferramentas


class TestFerramentas(unittest.TestCase):
    def test_no_binaries_fail_closed(self):
        with patch.object(ferramentas.shutil, "which", return_value=None):
            state = ferramentas.doctor()
        self.assertFalse(state["ready_for_pilot"])
        self.assertFalse(state["docker_image_local"])
        self.assertFalse(state["required"]["claude"])

    def test_pilot_requires_supported_flags_subscription_and_local_image(self):
        def fake(args):
            if args == ["claude", "auth", "status"]:
                return subprocess.CompletedProcess(args, 0, '{"authMethod":"claude.ai"}', "")
            if args == ["codex", "login", "status"]:
                return subprocess.CompletedProcess(args, 0, "Logged in using ChatGPT", "")
            return subprocess.CompletedProcess(args, 0,
                  "--restricted --safe-mode --no-session-persistence --permission-prompts --tools --sandbox --json --ask-for-approval", "")
        with patch.object(ferramentas.shutil, "which", return_value="/bin/tool"), \
             patch.object(ferramentas, "call", side_effect=fake):
            state = ferramentas.doctor()
        self.assertTrue(state["ready_for_pilot"])
        self.assertTrue(state["docker_image_local"])
        self.assertEqual(state["authentication"]["claude"], "subscription")
        self.assertEqual(state["authentication"]["codex"], "subscription")

    def test_api_billing_auth_is_blocked_without_secret_exposure(self):
        def fake(args):
            if args == ["claude", "auth", "status"]:
                return subprocess.CompletedProcess(args, 0, '{"authMethod":"api_key","secret":"SHOULD_NOT_LEAK"}', "")
            if args == ["codex", "login", "status"]:
                return subprocess.CompletedProcess(args, 0, "Logged in using API key", "")
            return subprocess.CompletedProcess(args, 0,
                  "--restricted --safe-mode --no-session-persistence --permission-prompts --tools --sandbox --json --ask-for-approval", "")
        with patch.object(ferramentas.shutil, "which", return_value="/bin/tool"), \
             patch.object(ferramentas, "call", side_effect=fake):
            state = ferramentas.doctor()
        self.assertFalse(state["ready_for_pilot"])
        self.assertEqual(state["authentication"]["claude"], "external_billing_blocked")
        self.assertEqual(state["authentication"]["codex"], "external_billing_blocked")
        self.assertNotIn("SHOULD_NOT_LEAK", str(state))

    def test_auth_status_failure_blocks_pilot(self):
        def fake(args):
            if args in (["claude", "auth", "status"], ["codex", "login", "status"]):
                return subprocess.CompletedProcess(args, 1, "", "not logged in")
            return subprocess.CompletedProcess(args, 0,
                  "--restricted --safe-mode --no-session-persistence --permission-prompts --tools --sandbox --json --ask-for-approval", "")
        with patch.object(ferramentas.shutil, "which", return_value="/bin/tool"), \
             patch.object(ferramentas, "call", side_effect=fake):
            self.assertFalse(ferramentas.doctor()["ready_for_pilot"])

    def test_claude_new_version_enables_flags_missing_from_help(self):
        def fake(args):
            if args == ["claude", "--version"]:
                return subprocess.CompletedProcess(args, 0, "2.1.270 (Claude Code)", "")
            if args == ["claude", "--help"]:
                return subprocess.CompletedProcess(args, 0, "claude -p --help", "")
            if args == ["codex", "exec", "--help"]:
                return subprocess.CompletedProcess(args, 0, "--json --sandbox", "")
            if args == ["codex", "--help"]:
                return subprocess.CompletedProcess(args, 0, "--ask-for-approval", "")
            if args == ["claude", "auth", "status"]:
                return subprocess.CompletedProcess(args, 0, '{"authMethod":"claude.ai"}', "")
            if args == ["codex", "login", "status"]:
                return subprocess.CompletedProcess(args, 0, "Logged in using ChatGPT", "")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(ferramentas.shutil, "which", return_value="/bin/tool"), \
             patch.object(ferramentas, "call", side_effect=fake):
            output = ferramentas.doctor(image="nivon-agentes:test-py311")
        self.assertTrue(output["ready_for_pilot"])
        self.assertEqual(output["claude_version"], "2.1.270")
        self.assertEqual(output["flag_validation"]["claude"], "version_and_documentation")
        self.assertTrue(all(output["supported_flags"]["codex"].values()))

    def test_unknown_older_version_with_missing_flags_is_blocked(self):
        def fake(args):
            if args == ["claude", "--version"]:
                return subprocess.CompletedProcess(args, 0, "2.1.200", "")
            if args == ["claude", "--help"]:
                return subprocess.CompletedProcess(args, 0, "--tools", "")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(ferramentas.shutil, "which", return_value="/bin/tool"), \
             patch.object(ferramentas, "call", side_effect=fake):
            state = ferramentas.doctor()
        self.assertFalse(state["ready_for_pilot"])
        self.assertFalse(state["supported_flags"]["claude"]["--restricted"])

    def test_reject_arbitrary_container_image(self):
        with patch.object(ferramentas.shutil, "which", return_value="/bin/tool"), \
             patch.dict("os.environ", {"NIVON_PYTHON_IMAGE": "untrusted:latest"}):
            state = ferramentas.doctor()
        self.assertFalse(state["docker_image_allowed"])
        self.assertFalse(state["ready_for_pilot"])


if __name__ == "__main__":
    unittest.main()
