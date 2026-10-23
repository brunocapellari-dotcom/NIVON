"""Execucao unica no runner CI para evidenciar coletor values-only REAL.
Nao grava bytes, banco ou artefato; remove-se apos aprovacao.
"""
import json
import os
import unittest
from nivon.pecuaria_sidra_quarentena import executar_captura_values_quarentena

class TestCapturaRealPontual(unittest.TestCase):
    def test_seis_consultas_efetivas_sem_persistencia(self):
        if (os.getenv("GITHUB_HEAD_REF") != "feat/pecuaria-inteligencia-20261020"
            or os.getenv("GITHUB_REPOSITORY") != "brunocapellari-dotcom/NIVON"):
            self.skipTest("apenas rodada unica de homologacao preliminar em CI")
        r=executar_captura_values_quarentena(
            periodo="202602",rede=True,direitos_confirmados=True,
            gravar=False,timeout=8)
        self.assertEqual(len(r["capturas"]),6)
        self.assertFalse(r["gravado"])
        self.assertTrue(r["consulta_externa_executada"])
        self.assertFalse(r["publicacao_historica_confirmada"])
        self.assertFalse(r["metadata_v3_confirmado"])
        self.assertFalse(r["homologado"])
        print("COLETOR_QUARENTENA_REAL_PREVIEW="+json.dumps({
            "status":r["status"],
            "capturas":r["capturas"],
            "cobertura":[{"especie":x["especie"],
                          "indicadores":[{
                            "indicador":i["indicador"],
                            "ufs_numericas":i["quantidade_ufs_numericas"],
                            "ufs_censuradas":i["quantidade_ufs_censuradas"],
                            "ufs_nao_presentes":i["ufs_nao_presentes"]}
                            for i in x["indicadores"]]}
                         for x in r["diagnosticos"]],
            "gravado":r["gravado"],"metadata_v3_confirmado":False,
            "publicacao_permitida":False},ensure_ascii=False,sort_keys=True),flush=True)
