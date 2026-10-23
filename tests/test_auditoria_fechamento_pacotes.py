"""Regressões do fechamento incondicional de Requires-Dist, somente offline."""
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
from datetime import datetime, timezone

from nivon.auditoria_fechamento_pacotes import (
    analisar_fechamento, auditar,
)
from nivon.auditoria_artefatos_pacotes import verificar_cadeia
from nivon.auditoria_evidencias_pacotes import ErroEvidencia


def wheel(nome: str, versao: str, dependencias: tuple[str, ...] = ()) -> bytes:
    prefix = f"{nome}-{versao}.dist-info"
    payload = {
        f"{prefix}/METADATA": (
            f"Metadata-Version: 2.1\nName: {nome}\nVersion: {versao}\n" +
            "".join(f"Requires-Dist: {req}\n" for req in dependencias)
        ).encode("utf-8"),
        f"{prefix}/WHEEL": b"Wheel-Version: 1.0\n",
        f"{nome}/__init__.py": b"# synthetic\n",
    }
    rows = []
    for path, data in payload.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        rows.append((path, "sha256=" + digest, str(len(data))))
    rows.append((f"{prefix}/RECORD", "", ""))
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in payload.items():
            zf.writestr(path, data)
        zf.writestr(f"{prefix}/RECORD", output.getvalue().encode())
    return raw.getvalue()


class FechamentoWheelTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.project = (
            '[project]\nname = "nivon"\nrequires-python = ">=3.11"\n'
            'dependencies = []\n'
            '[project.optional-dependencies]\n'
            'ivo-query = ["duckdb>=1,<2"]\n'
        )
        self.extras = ["ivo-query"]
        self._fill(("numpy>=1,<3",), ("duckdb", "1.2.0"))

    def _fill(self, depends=(), primary=("duckdb", "1.2.0")):
        for file in self.root.iterdir():
            if file.is_file():
                file.unlink()
        self.deps = ((primary[0], primary[1], depends), ("numpy", "2.0.0", ()))
        self.lock = ""
        items = []
        for name, version, requirements in self.deps:
            data = wheel(name, version, requirements)
            (self.root / f"{name}-{version}-py3-none-any.whl").write_bytes(data)
            self.lock += f"{name}=={version} --hash=sha256:{hashlib.sha256(data).hexdigest()}\n"
            items.append({"name": name, "version": version, "vulns": []})
        self.report = json.dumps({"dependencies": items, "fixes": []})
        h = lambda s: hashlib.sha256(s.encode()).hexdigest()
        self.meta = {
            "pyproject_sha256": h(self.project), "lock_sha256": h(self.lock),
            "report_sha256": h(self.report), "tool": "pip-audit",
            "service": "pypi", "exit_code": 0,
            "generated_at": "2026-10-21T12:00:00Z",
            "extras": list(self.extras),
        }

    def _run(self):
        return auditar(self.root, self.project, self.lock, self.extras)

    def test_valid_unconditional_graph_from_actual_synthetic_wheels(self):
        result = self._run()
        self.assertEqual(result["locked_package_count"], 2)
        self.assertEqual(result["declared_edges_checked"], 2)
        self.assertTrue(result["unconditional_supported_requirements_consistent"])
        self.assertFalse(result["resolver_transitive_closure_attested"])
        self.assertFalse(result["approved_for_production"])

    def test_parenthesized_requirement_accepted(self):
        self._fill(("numpy (>=1,<3)",))
        self.assertEqual(self._run()["declared_edges_checked"], 2)

    def test_missing_transitive_package_fails_closed(self):
        self._fill(("missing>=1,<3",))
        with self.assertRaisesRegex(ErroEvidencia, "ausente do lock"):
            self._run()

    def test_version_constraint_violated_fails(self):
        self._fill(("numpy>=3,<4",))
        with self.assertRaisesRegex(ErroEvidencia, "incompatível"):
            self._run()

    def test_marker_cannot_be_silently_ignored(self):
        for req in ("numpy>=1; python_version < '3.12'",
                    "numpy>=1; extra == 'plot'",
                    "numpy[plot]>=1,<3"):
            with self.subTest(req=req):
                self._fill((req,))
                with self.assertRaisesRegex(ErroEvidencia, "Requires-Dist"):
                    self._run()

    def test_non_numeric_and_bare_versions_blocked(self):
        for req in ("numpy~=2.0", "numpy!=1.2", "numpy"):
            with self.subTest(req=req):
                self._fill((req,))
                with self.assertRaisesRegex(ErroEvidencia, "Requires-Dist"):
                    self._run()

    def test_extra_selected_and_unselected_protection(self):
        self.extras = ["not-in-project"]
        with self.assertRaisesRegex(ErroEvidencia, "extra selecionado"):
            self._run()

    def test_duplicate_extras_rejected(self):
        self.extras = ["ivo-query", "ivo-query"]
        with self.assertRaisesRegex(ErroEvidencia, "duplicado"):
            self._run()

    def test_invalid_forged_record_flag_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "RECORD"):
            analisar_fechamento(self.project, self.lock, {
                "wheel_record_integrity_verified": False,
                "verified_wheels": [],
            }, ["ivo-query"])

    def test_untrusted_missing_requires_dist_rejected(self):
        data = {"wheel_record_integrity_verified": True,
                "verified_wheels": [
                    {"distribution": "duckdb", "version": "1.2.0",
                     "record_integrity_verified": True},
                    {"distribution": "numpy", "version": "2.0.0",
                     "record_integrity_verified": True},
                ]}
        with self.assertRaisesRegex(ErroEvidencia, "dependências auditáveis"):
            analisar_fechamento(self.project, self.lock, data, ["ivo-query"])

    def test_valid_composed_gate_remains_blocked_for_release(self):
        result = verificar_cadeia(
            self.project, self.lock, self.report, self.meta, self.root,
            agora=datetime(2026, 10, 21, 12, 10, tzinfo=timezone.utc))
        self.assertEqual(result["supported_wheel_dependencies_checked"], 2)
        self.assertTrue(result["supported_wheel_dependencies_consistent"])
        self.assertFalse(result["resolver_transitive_closure_attested"])
        self.assertFalse(result["approved_for_production"])

    def test_composed_gate_rejects_unsatisfied_transitive_requirement(self):
        self._fill(("numpy>=3,<4",))
        with self.assertRaisesRegex(ErroEvidencia, "incompatível"):
            verificar_cadeia(
                self.project, self.lock, self.report, self.meta, self.root,
                agora=datetime(2026, 10, 21, 12, 10, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
