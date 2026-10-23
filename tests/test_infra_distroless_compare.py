"""Uma prova distroless só vale com SBOM dos três pacotes e runtime executado."""
from pathlib import Path
import unittest
from nivon.infra_distroless_compare import comparar
from nivon.infra_supplychain import ErroSupplyChain

DIGEST="gcr.io/distroless/cc-debian13@sha256:"+"a"*64


def scan(name,severities):
    return {"SchemaVersion":2,"ArtifactName":name,"ArtifactType":"container_image",
            "Results":[{"Class":"os-pkgs","Target":"synthetic-os",
                        "Vulnerabilities":[{"Severity":s} for s in severities]}]}


def bom(names=("agrobr","pandas","statsforecast")):
    return {"bomFormat":"CycloneDX","specVersion":"1.6",
            "components":[{"name":s} for s in names]}


class TestDistrolessExperiment(unittest.TestCase):
    def test_same_dependencies_and_blocked_release(self):
        result=comparar(scan("nivon-analytics:ci",["HIGH"]*44),
                         scan("nivon-analytics:distroless",[]),bom(),
                         arch="arm64",base=DIGEST,runtime_passed=True)
        self.assertEqual(result["delta_blocking"],-44)
        self.assertTrue(result["distroless_zero_high_critical"])
        self.assertFalse(result["production_authorized"])
        self.assertFalse(result["security_licensing_verified"])

    def test_wrong_image_digest_sbom_and_runtime_fail(self):
        left=scan("nivon-analytics:ci",["HIGH"])
        right=scan("nivon-analytics:distroless",[])
        for kw in [
            dict(arch="amd64",base="gcr.io/distroless/cc-debian13:nonroot",runtime_passed=True),
            dict(arch="arm64",base=DIGEST,runtime_passed=False),
            dict(arch="s390x",base=DIGEST,runtime_passed=True),
        ]:
            with self.assertRaises(ErroSupplyChain):
                comparar(left,right,bom(),**kw)
        with self.assertRaises(ErroSupplyChain):
            comparar(left,right,bom(("agrobr","pandas")),
                     arch="amd64",base=DIGEST,runtime_passed=True)

    def test_dockerfile_digest_required_and_ci_has_network_guard(self):
        root=Path(__file__).resolve().parents[1]
        d=(root/"infra/docker/Dockerfile.analytics-distroless").read_text()
        w=(root/".github/workflows/infra_analytics_experiment.yml").read_text()
        self.assertIn("FROM ${DISTROLESS_BASE}",d)
        self.assertIn("COPY --from=analytics-source /usr/local/",d)
        self.assertIn("USER 65532:65532",d)
        self.assertIn('ENTRYPOINT ["/usr/local/bin/python"',d)
        self.assertIn("--build-arg \"DISTROLESS_BASE=$distroless_digest\"",w)
        self.assertIn("infra_distroless_compare",w)
        self.assertIn("--network=none",w)
        self.assertIn("NIVON_DISTROLESS_EXPERIMENT_ONLY",w)
        self.assertIn("NIVON_DISTROLESS_IMPORT_BLOCKED",w)
        self.assertIn("83b9b50586253821cf63ffcec87d3d94265a093ad30da232039af962dd8f4edf",(root/"infra/docker/Dockerfile.analytics-distroless").read_text())
        for bad in ("docker push", "continue-on-error: true","secrets."):
            self.assertNotIn(bad,w)


if __name__=="__main__":
    unittest.main()
