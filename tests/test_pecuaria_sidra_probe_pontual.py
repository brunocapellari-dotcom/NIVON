"""SONDAGEM TEMPORARIA (remover apos coletar resultado de CI).
Nenhum payload e escrito, nao publica dado e nao afirma homologacao.
"""
import json
import os
import unittest
from nivon.pecuaria_sidra_sondagem import sondar_tres_cadeias

class TestSondagemPontualSIDRA(unittest.TestCase):
    def test_acesso_https_do_runner_da_pr22(self):
        if (os.getenv("GITHUB_HEAD_REF") != "feat/pecuaria-inteligencia-20261020"
            or os.getenv("GITHUB_REPOSITORY") != "brunocapellari-dotcom/NIVON"):
            self.skipTest("somente uma sondagem da branch pecuaria no CI")
        diag = sondar_tres_cadeias(periodo="202602", rede=True, timeout=4)
        print("DIAGNOSTICO_PONTUAL_SIDRA=" + json.dumps(
            diag, sort_keys=True, ensure_ascii=False), flush=True)
        self.assertEqual(len(diag["cadeias"]), 3)
        self.assertTrue(all(not x["homologado"] for x in diag["cadeias"]))
