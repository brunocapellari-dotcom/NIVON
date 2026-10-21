"""Wheelhouse fixture-based tests: no package installation, network or execution."""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from nivon.auditoria_evidencias_pacotes import ErroEvidencia
from nivon.auditoria_wheelhouse import verificar


def gerar_wheel(name="example", version="1.2.3", metadata_name=None,
                metadata_version=None, extra=None, wheel_header=True):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as z:
        folder = f"{name}-{version}.dist-info"
        z.writestr(folder + "/METADATA",
                   f"Metadata-Version: 2.1\nName: {metadata_name or name}\n"
                   f"Version: {metadata_version or version}\n")
        if wheel_header:
            z.writestr(folder + "/WHEEL", "Wheel-Version: 1.0\nGenerator: fixture\n")
        z.writestr(name + "/__init__.py", "# fixture only, not executed\n")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return bio.getvalue()


class WheelhouseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bytes = gerar_wheel()
        self.path = self.base / "example-1.2.3-py3-none-any.whl"
        self.path.write_bytes(self.bytes)
        self.lock = self.lock_for(self.bytes)

    @staticmethod
    def lock_for(raw, distribution="example", version="1.2.3"):
        return f"{distribution}=={version} --hash=sha256:{hashlib.sha256(raw).hexdigest()}\n"

    def result(self):
        return verificar(self.base, self.lock)

    def test_real_bytes_and_headers_verified_without_install(self):
        result = self.result()
        self.assertEqual(result["wheel_count"], 1)
        self.assertEqual(result["verified_wheels"][0]["verified_sha256"],
                         hashlib.sha256(self.bytes).hexdigest())
        self.assertTrue(result["package_files_sha256_verified_against_declarations"])
        self.assertTrue(result["wheel_identity_headers_checked"])
        for blocked in ("wheel_record_integrity_verified", "wheel_tags_platform_compatible",
                        "dependency_closure_verified", "provenance_authenticated",
                        "vulnerabilities_scanned", "licenses_reviewed",
                        "packages_installed", "approved_for_install",
                        "approved_for_production"):
            with self.subTest(blocked=blocked):
                self.assertFalse(result[blocked])
        self.assertTrue(result["release_gate"].startswith("BLOCKED_"))

    def test_modified_wheel_bytes_dont_match_lock(self):
        self.path.write_bytes(self.bytes + b"tamper")
        with self.assertRaisesRegex(ErroEvidencia, "SHA256"):
            self.result()

    def test_metadata_name_mismatch_fails_even_with_correct_hash(self):
        raw = gerar_wheel(metadata_name="different")
        self.path.write_bytes(raw)
        self.lock = self.lock_for(raw)
        with self.assertRaisesRegex(ErroEvidencia, "divergentes"):
            self.result()

    def test_metadata_version_mismatch_fails(self):
        raw = gerar_wheel(metadata_version="1.2.4")
        self.path.write_bytes(raw)
        self.lock = self.lock_for(raw)
        with self.assertRaisesRegex(ErroEvidencia, "divergentes"):
            self.result()

    def test_dist_info_directory_mismatch(self):
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as z:
            z.writestr("other-1.2.3.dist-info/METADATA", "Name: example\nVersion: 1.2.3\n")
            z.writestr("other-1.2.3.dist-info/WHEEL", "Wheel-Version: 1.0\n")
        raw = bio.getvalue()
        self.path.write_bytes(raw)
        self.lock = self.lock_for(raw)
        with self.assertRaisesRegex(ErroEvidencia, "dist-info difere"):
            self.result()

    def test_wheel_header_missing_is_rejected(self):
        raw = gerar_wheel(wheel_header=False)
        self.path.write_bytes(raw)
        self.lock = self.lock_for(raw)
        with self.assertRaisesRegex(ErroEvidencia, "WHEEL ausente"):
            self.result()

    def test_zip_path_traversal_rejected(self):
        raw = gerar_wheel(extra={"../../evil": "never extracted"})
        self.path.write_bytes(raw)
        self.lock = self.lock_for(raw)
        with self.assertRaisesRegex(ErroEvidencia, "caminho inseguro"):
            self.result()
        self.assertFalse((self.base.parent / "evil").exists())

    def test_duplicate_zip_member_rejected(self):
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as z:
            z.writestr("example-1.2.3.dist-info/METADATA", "Name: example\nVersion: 1.2.3\n")
            z.writestr("example-1.2.3.dist-info/WHEEL", "Wheel-Version: 1.0\n")
            with patch("warnings.warn"):
                z.writestr("example-1.2.3.dist-info/WHEEL", "Wheel-Version: 1.0\n")
        raw = bio.getvalue()
        self.path.write_bytes(raw)
        self.lock = self.lock_for(raw)
        with self.assertRaisesRegex(ErroEvidencia, "duplicado"):
            self.result()

    def test_symlink_file_rejected(self):
        self.path.unlink()
        original = self.base.parent / ("external-synthetic-" + self.base.name + ".whl")
        original.write_bytes(self.bytes)
        self.addCleanup(original.unlink)
        self.path.symlink_to(original)
        with self.assertRaisesRegex(ErroEvidencia, "symlink"):
            self.result()

    def test_symlink_wheelhouse_root_rejected(self):
        root_link = self.base.parent / ("wheelhouse-link-" + self.base.name)
        root_link.symlink_to(self.base, target_is_directory=True)
        self.addCleanup(root_link.unlink)
        with self.assertRaisesRegex(ErroEvidencia, "symlink"):
            verificar(root_link, self.lock)

    def test_unlisted_wheel_rejected(self):
        (self.base / "other-2.0-py3-none-any.whl").write_bytes(gerar_wheel("other", "2.0"))
        with self.assertRaisesRegex(ErroEvidencia, "extra"):
            self.result()

    def test_missing_locked_wheel_rejected(self):
        self.lock += "missing==1.0 --hash=sha256:" + "0" * 64 + "\n"
        with self.assertRaisesRegex(ErroEvidencia, "não cobre"):
            self.result()

    def test_second_wheel_for_same_package_rejected(self):
        (self.base / "example-1.2.3-py3-none-manylinux.whl").write_bytes(self.bytes)
        with self.assertRaisesRegex(ErroEvidencia, "mais de um"):
            self.result()

    def test_sdist_or_unexpected_file_rejected(self):
        (self.base / "setup.py").write_text("raise SystemExit('not executed')\n")
        with self.assertRaisesRegex(ErroEvidencia, "não é wheel"):
            self.result()

    def test_broken_zip_rejected_even_hash_matches(self):
        raw = b"this is not a wheel"
        self.path.write_bytes(raw)
        self.lock = self.lock_for(raw)
        with self.assertRaisesRegex(ErroEvidencia, "ZIP"):
            self.result()

    def test_version_outside_numeric_subcontract_fails_closed(self):
        self.path.unlink()
        (self.base / "example-1.0rc1-py3-none-any.whl").write_bytes(self.bytes)
        with self.assertRaisesRegex(ErroEvidencia, "versão"):
            self.result()

    def test_member_count_limit(self):
        with patch("nivon.auditoria_wheelhouse.MAX_ENTRIES", 2):
            with self.assertRaisesRegex(ErroEvidencia, "excesso"):
                self.result()

    def test_filename_does_not_match_locked_version(self):
        self.path.rename(self.base / "example-2.0-py3-none-any.whl")
        with self.assertRaisesRegex(ErroEvidencia, "identidade|versão"):
            self.result()

    def test_no_execution_of_wheel_code(self):
        content = gerar_wheel(extra={
            "example/malicious.py": "raise Exception('must not execute')",
            "example/scripts.pth": "import os; os.system('echo never')",
        })
        self.path.write_bytes(content)
        self.lock = self.lock_for(content)
        result = self.result()
        self.assertEqual(result["wheel_count"], 1)
        self.assertFalse(result["packages_installed"])


if __name__ == "__main__":
    unittest.main()
