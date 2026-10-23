"""Proposta OCI Always Free: limites teóricos não habilitam recursos pagos."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nivon.infra_oci_quota import ErroCotaOCI, carregar_proposta, avaliar_proposta


class TestOCIQuota(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=carregar_proposta()

    def setUp(self):
        self.d=copy.deepcopy(self.base)

    def test_proposta_na_referencia_nao_garante_zero_custo(self):
        res=avaliar_proposta(self.d)
        self.assertEqual(res["estado"],"CANDIDATO_COMPATIVEL_SOZINHO_CONTA_DESCONHECIDA")
        self.assertEqual(res["proposta"]["a1_ocpu_hours_month"],744)
        self.assertEqual(res["proposta"]["a1_memory_gb_hours_month"],2976)
        self.assertFalse(res["deploy_autorizado"])
        self.assertFalse(res["estimativa_de_custo_zero_garantida"])

    def test_limite_31_dias_2ocpu_12gb_cabe_na_referencia(self):
        self.d["nivon_candidate"]["ocpus"]=2
        self.d["nivon_candidate"]["memory_gb"]=12
        result=avaliar_proposta(self.d)
        self.assertEqual(result["proposta"]["a1_ocpu_hours_month"],1488)
        self.assertEqual(result["proposta"]["a1_memory_gb_hours_month"],8928)
        self.assertEqual(result["excede_referencia"],[])
        self.assertFalse(result["quota_restante_comprovada"])

    def test_proposta_excessiva_e_apontada(self):
        self.d["nivon_candidate"]["ocpus"]=3
        self.d["nivon_candidate"]["memory_gb"]=16
        r=avaliar_proposta(self.d)
        self.assertEqual(r["estado"],"PROPOSTA_FORA_DA_REFERENCIA")
        self.assertIn("a1_ocpus_total",r["excede_referencia"])
        self.assertIn("a1_memory_gb_total",r["excede_referencia"])

    def test_boot_e_bloco_compartilham_cota(self):
        self.d["nivon_candidate"]["additional_block_gb"]=160
        r=avaliar_proposta(self.d)
        self.assertIn("boot_and_block_gb_total",r["excede_referencia"])

    def test_mais_objetos_que_limite_e_apontado(self):
        self.d["nivon_candidate"]["object_gb"]=21
        self.assertIn("object_storage_gb_total",avaliar_proposta(self.d)["excede_referencia"])

    def test_nao_presume_consumo_da_holding(self):
        self.d["tenant_evidence"]["other_a1_ocpus_used"]=1
        with self.assertRaises(ErroCotaOCI):
            avaliar_proposta(self.d)

    def test_regiao_nao_homologada_por_json(self):
        self.d["tenant_evidence"]["home_region_verified"]=True
        with self.assertRaises(ErroCotaOCI):
            avaliar_proposta(self.d)

    def test_bloqueia_upgrade_pago(self):
        self.d["limits"]["automatic_upgrade"]=True
        with self.assertRaises(ErroCotaOCI):
            avaliar_proposta(self.d)

    def test_bloqueia_ipv4_e_portas_publicas(self):
        self.d["nivon_candidate"]["public_ports_requested"]=[443]
        with self.assertRaises(ErroCotaOCI):
            avaliar_proposta(self.d)

    def test_bloqueia_shape_nao_revisada(self):
        self.d["nivon_candidate"]["shape"]="VM.Standard.E4.Flex"
        with self.assertRaises(ErroCotaOCI):
            avaliar_proposta(self.d)

    def test_bloqueia_false_numerico_e_zero_cpu(self):
        self.d["nivon_candidate"]["ocpus"]=False
        with self.assertRaises(ErroCotaOCI):
            avaliar_proposta(self.d)
        self.d["nivon_candidate"]["ocpus"]=0
        with self.assertRaises(ErroCotaOCI):
            avaliar_proposta(self.d)

    def test_sem_chaves_json_duplicadas(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"bad.json"
            p.write_text('{"schema":"x","schema":"y"}',encoding="utf-8")
            with self.assertRaises(ErroCotaOCI):
                carregar_proposta(p)

    def test_cli_sem_cloud(self):
        root=Path(__file__).resolve().parents[1]
        env=dict(os.environ,PYTHONPATH=str(root/"src"))
        base=[sys.executable,"-m","nivon.infra_oci_quota"]
        result=subprocess.run(base,env=env,cwd=root,text=True,capture_output=True,
                              timeout=20,check=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(json.loads(result.stdout)["deploy_autorizado"])
        fail=subprocess.run(base+["--require-account-proof"],env=env,cwd=root,
                            text=True,capture_output=True,timeout=20,check=False)
        self.assertEqual(fail.returncode,3)


if __name__=="__main__":
    unittest.main()
