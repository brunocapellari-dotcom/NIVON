"""Metadados do pacote nunca são permissão de uso de dados de terceiros."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from nivon.infra_wheel_license_audit import auditar, _classificar
from nivon.infra_wheel_lock import coletar
from nivon.infra_supplychain import ErroSupplyChain


class TestWheelLicenseMetadata(unittest.TestCase):
    def test_lock_e_metadata_sao_obrigatorios_sem_conceder_direitos(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            files=root/"wheels"
            files.mkdir()
            samples=[
                ("aa-1-py3-none-any.whl","License-Expression: MIT"),
                ("bb-1-py3-none-any.whl","License: Apache-2.0"),
                ("cc-1-py3-none-any.whl","Classifier: License :: OSI Approved"),
            ]
            for filename,header in samples:
                with ZipFile(files/filename,"w") as z:
                    name=filename.split("-")[0]
                    z.writestr(f"{name}-1.dist-info/METADATA",
                               f"Metadata-Version: 2.4\nName: {name}\nVersion: 1\n{header}\n")
            observed=coletar(files,"amd64")
            lock=root/"lock.json"
            lock.write_text(json.dumps(observed))
            report=auditar(files,"amd64",lock)
            self.assertEqual(report["verified_locked_wheels"],3)
            self.assertEqual(report["declaracoes_por_formato"]["spdx_declarado"],1)
            self.assertEqual(report["declaracoes_por_formato"]["licenca_legada_declarada"],1)
            self.assertEqual(report["declaracoes_por_formato"]["classificador_licenca"],1)
            self.assertFalse(report["cepea_imea_conab_republication_authorized"])
            self.assertFalse(report["production_authorized"])
            with ZipFile(files/samples[0][0],"a") as z:
                z.writestr("attack.txt","changed")
            with self.assertRaises(ErroSupplyChain):
                auditar(files,"amd64",lock)

    def test_metadado_vazio_ou_malformado_bloqueia(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"missing-1-py3-none-any.whl"
            with ZipFile(p,"w") as z:
                z.writestr("x.txt","missing")
            with self.assertRaises(ErroSupplyChain):
                _classificar(p)

    def test_ci_mesmo_workflow_sem_rede_apos_download(self):
        root=Path(__file__).resolve().parents[1]
        w=(root/".github/workflows/infra_analytics_experiment.yml").read_text()
        self.assertIn("infra_wheel_license_audit",w)
        self.assertIn("--lock",w)
        self.assertLess(w.index("infra_wheel_license_audit"),w.index("Build analítico"))
        self.assertNotIn("upload-artifact@",w)
        self.assertNotIn("docker push",w)


if __name__=="__main__":
    unittest.main()
