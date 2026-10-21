"""Testes offline de licença PEP639 em wheels sintéticos íntegros."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from nivon.auditoria_evidencias_pacotes import ErroEvidencia
from nivon.auditoria_licencas_pacotes import auditar, inventariar_licencas


def criar_wheel(*, versao_meta="2.4", expression="MIT", legacy=None,
                declared=("LICENSE",), binary=None, missing=(),
                other_headers=()):
    prefix = "example-1.2.3.dist-info"
    metadata = [
        f"Metadata-Version: {versao_meta}",
        "Name: example",
        "Version: 1.2.3",
    ]
    if expression is not None:
        metadata.append("License-Expression: " + expression)
    if legacy is not None:
        metadata.append("License: " + legacy)
    metadata.extend("License-File: " + name for name in declared)
    metadata.extend(other_headers)
    members = {
        prefix + "/METADATA": ("\n".join(metadata) + "\n").encode(),
        prefix + "/WHEEL": b"Wheel-Version: 1.0\n",
        "example/__init__.py": b"# no third party code is executed\n",
    }
    for path in declared:
        if path not in missing and not path.startswith(("../", "/")):
            members[prefix + "/licenses/" + path] = (
                binary if binary is not None else b"Test license fixture\n"
            )
    rows = []
    for name, data in members.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        rows.append([name, "sha256=" + digest, str(len(data))])
    rows.append([prefix + "/RECORD", "", ""])
    out = io.StringIO(newline="")
    csv.writer(out, lineterminator="\n").writerows(rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
        z.writestr(prefix + "/RECORD", out.getvalue().encode())
    return buffer.getvalue()


class LicencaWheelTests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory()
        self.addCleanup(self.context.cleanup)
        self.root = Path(self.context.name)
        self.wheel = self.root / "example-1.2.3-py3-none-any.whl"
        self.store(criar_wheel())

    def store(self, raw):
        self.wheel.write_bytes(raw)
        self.lock = ("example==1.2.3 --hash=sha256:" +
                     hashlib.sha256(raw).hexdigest() + "\n")

    def evaluate(self):
        return auditar(self.root, self.lock)

    def test_modern_metadata_has_verified_license_file_but_not_legal_approval(self):
        result = self.evaluate()
        self.assertEqual(result["packages_review_pending"], 1)
        self.assertEqual(result["packages_modern_metadata"], 1)
        self.assertEqual(result["declared_license_files"], 1)
        pkg = result["distributions"][0]
        self.assertEqual(pkg["license_expression_declared"], "MIT")
        self.assertEqual(pkg["status"], "SPDX_EXPRESSION_DECLARED_UNVERIFIED")
        self.assertTrue(pkg["license_files"][0]["utf8_checked"])
        self.assertEqual(pkg["license_files"][0]["verified_path"],
                         "example-1.2.3.dist-info/licenses/LICENSE")
        self.assertEqual(pkg["license_files"][0]["sha256"],
                         hashlib.sha256(b"Test license fixture\n").hexdigest())
        self.assertFalse(result["spdx_identifiers_validated_against_spdx_list"])
        self.assertFalse(result["legal_review_completed"])
        self.assertFalse(result["approved_for_production"])

    def test_expression_without_license_file_still_needs_review(self):
        self.store(criar_wheel(declared=()))
        result = self.evaluate()
        self.assertEqual(result["declared_license_files"], 0)
        self.assertEqual(result["distributions"][0]["status"],
                         "SPDX_EXPRESSION_DECLARED_UNVERIFIED")

    def test_missing_expression_not_misreported_as_mit(self):
        self.store(criar_wheel(expression=None, declared=()))
        pkg = self.evaluate()["distributions"][0]
        self.assertIsNone(pkg["license_expression_declared"])
        self.assertEqual(pkg["status"], "SPDX_EXPRESSION_ABSENT_MANUAL_REVIEW")

    def test_license_expression_not_legal_certificate(self):
        self.store(criar_wheel(expression="LicenseRef-Proprietary", declared=()))
        result = self.evaluate()
        self.assertEqual(result["distributions"][0]["license_expression_declared"],
                         "LicenseRef-Proprietary")
        self.assertFalse(result["actual_license_compatibility_verified"])

    def test_missing_declared_license_file_blocks(self):
        self.store(criar_wheel(missing=("LICENSE",)))
        with self.assertRaisesRegex(ErroEvidencia, "não existe"):
            self.evaluate()

    def test_path_traversal_license_path_blocks(self):
        self.store(criar_wheel(declared=("../outside",)))
        with self.assertRaisesRegex(ErroEvidencia, "caminho inseguro"):
            self.evaluate()

    def test_duplicate_license_file_header_blocks(self):
        self.store(criar_wheel(declared=("LICENSE", "LICENSE")))
        with self.assertRaisesRegex(ErroEvidencia, "duplicado"):
            self.evaluate()

    def test_non_utf8_license_file_blocks(self):
        self.store(criar_wheel(binary=b"\xff\xfe"))
        with self.assertRaisesRegex(ErroEvidencia, "UTF-8"):
            self.evaluate()

    def test_conflicting_legacy_and_spdx_license_metadata_blocks(self):
        self.store(criar_wheel(legacy="MIT"))
        with self.assertRaisesRegex(ErroEvidencia, "mutuamente exclusivas"):
            self.evaluate()

    def test_duplicate_license_expression_blocks(self):
        self.store(criar_wheel(other_headers=("License-Expression: Apache-2.0",)))
        with self.assertRaisesRegex(ErroEvidencia, "duplicados"):
            self.evaluate()

    def test_legacy_metadata_does_not_claim_path_checked(self):
        self.store(criar_wheel(versao_meta="2.1", expression=None, legacy="MIT"))
        pkg = self.evaluate()["distributions"][0]
        self.assertEqual(pkg["status"], "LEGACY_METADATA_MANUAL_REVIEW")
        self.assertFalse(pkg["license_files"][0]["path_checked"])

    def test_spdx_field_under_legacy_metadata_blocks(self):
        self.store(criar_wheel(versao_meta="2.1", expression="MIT"))
        with self.assertRaisesRegex(ErroEvidencia, "versão de METADATA"):
            self.evaluate()

    def test_license_path_separator_is_not_normalized_silently(self):
        self.store(criar_wheel(declared=("licenses\\LICENSE",)))
        with self.assertRaisesRegex(ErroEvidencia, "caminho inválido"):
            self.evaluate()

    def test_invalid_license_header_control_character_rejected(self):
        self.store(criar_wheel(expression="MIT\u2603", declared=()))
        with self.assertRaisesRegex(ErroEvidencia, "License-Expression"):
            self.evaluate()

    def test_missing_wheel_summary_license_evidence_fails_closed(self):
        with self.assertRaisesRegex(ErroEvidencia, "evidência de licença"):
            inventariar_licencas({
                "wheel_count": 1,
                "wheel_record_integrity_verified": True,
                "verified_wheels": [{
                    "distribution": "example", "version": "1.2.3",
                    "record_integrity_verified": True,
                }],
            })

    def test_unverified_record_fails_before_license_status(self):
        with self.assertRaisesRegex(ErroEvidencia, "RECORD"):
            inventariar_licencas({
                "wheel_count": 1, "wheel_record_integrity_verified": False,
                "verified_wheels": [],
            })


if __name__ == "__main__":
    unittest.main()
