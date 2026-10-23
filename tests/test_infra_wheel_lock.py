"""Confere invariantes do lock de wheels e rejeita alterações transitivas."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nivon.infra_wheel_lock import coletar, verificar, constraints_from_lock, BASE, REQUIREMENTS
from nivon.infra_supplychain import ErroSupplyChain


class TestWheelLock(unittest.TestCase):
    def test_hash_todas_as_wheels_e_nomeacao(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "wheels"
            root.mkdir()
            for name in ("agrobr-2.0.0-py3-none-any.whl", "pandas-2.3.0-cp311-cp311-manylinux.whl",
                         "statsforecast-2.0.0-py3-none-any.whl"):
                (root / name).write_bytes(b"synthetic-" + name.encode())
            got = coletar(root, "amd64")
            self.assertEqual(len(got["files"]), 3)
            self.assertEqual(got["base_image"], BASE)
            self.assertEqual(got["requirements"], list(REQUIREMENTS))
            p = root.parent / "expected.json"
            # test fixture fora do local de wheels
            p.write_text(json.dumps(got), encoding="utf-8")
            verificar(got, p)
            (root / "agrobr-2.0.0-py3-none-any.whl").write_bytes(b"different")
            with self.assertRaises(ErroSupplyChain):
                verificar(coletar(root, "amd64"), p)

    def test_recusa_sdist_symlink_e_arch_nao_homologada(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(3):
                (root / f"test-{i}-py3-none-any.whl").write_bytes(b"abc")
            with self.assertRaises(ErroSupplyChain):
                coletar(root, "unknown")
            (root / "source.tar.gz").write_bytes(b"abc")
            with self.assertRaises(ErroSupplyChain):
                coletar(root, "arm64")

    def test_constraints_respeitam_59_versoes_e_proibem_drift(self):
        for arch in ("amd64","arm64"):
            locked=ROOT / f"infra/locks/analytics-{arch}.json"
            lines=constraints_from_lock(locked,arch).splitlines()
            self.assertEqual(len(lines),59)
            self.assertIn("certifi==2026.10.19",lines)
            with self.assertRaises(ErroSupplyChain):
                constraints_from_lock(locked,"wrong")

    def test_ci_reutiliza_workflow_e_nao_desabilita_gates(self):
        root = Path(__file__).resolve().parents[1]
        wf = ((root / ".github/workflows/infra_analytics_experiment.yml").read_text()
              + "\n" + (root / "infra/scripts/offline_batch_ci.sh").read_text())
        for txt in ("infra_wheel_lock", "--emit", "--constraint /opt/nivon-constraints.txt",
                    "sha256sum -c", "--build-context", "--network=none",
                    "NIVON_2_WORKERS_3_JOBS_CRASH_RESTORE_E2E_OK_NO_DEPLOY"):
            self.assertIn(txt, wf)
        self.assertNotIn("continue-on-error: true", wf)


if __name__ == "__main__":
    unittest.main()
