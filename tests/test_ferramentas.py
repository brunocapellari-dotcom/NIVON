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

    def test_pilot_requires_supported_flags_and_local_image(self):
        def fake(args):
            return subprocess.CompletedProcess(args, 0,
                  "--restricted --bare --no-session-persistence --permission-prompts --tools --sandbox --json", "")
        with patch.object(ferramentas.shutil, "which", return_value="/bin/tool"), \
             patch.object(ferramentas, "call", side_effect=fake):
            state = ferramentas.doctor()
        self.assertTrue(state["ready_for_pilot"])
        self.assertTrue(state["docker_image_local"])

    def test_reject_arbitrary_container_image(self):
        with patch.object(ferramentas.shutil, "which", return_value="/bin/tool"), \
             patch.dict("os.environ", {"NIVON_PYTHON_IMAGE": "untrusted:latest"}):
            state = ferramentas.doctor()
        self.assertFalse(state["docker_image_allowed"])
        self.assertFalse(state["ready_for_pilot"])


if __name__ == "__main__":
    unittest.main()
