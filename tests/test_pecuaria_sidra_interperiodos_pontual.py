"""Sondagem descartavel de compatibilidade 2025-T2 e 2026-T1.

Somente SHA/contagens e status, sem gravar ou publicar valores brutos.
Retirar este arquivo apos leitura dos resultados do runner.
"""
import json
import os
import unittest
from nivon.pecuaria_sidra_backfill import executar_backfill_quarentena

class TestCompatibilidadeSIDRAInterperiodos(unittest.TestCase):
    def test_dois_trimestres_reais_somente_preview(self):
        if (os.getenv("GITHUB_HEAD_REF") != "feat/pecuaria-inteligencia-20261020"
            or os.getenv("GITHUB_REPOSITORY") != "brunocapellari-dotcom/NIVON"):
            self.skipTest("somente uma execucao real da branch pecuaria")
        out=executar_backfill_quarentena(
            periodos=["202502","202601"],rede=True,
            direitos_confirmados=True,gravar=False,timeout=8)
        self.assertEqual(out["n_capturas"],12)
        self.assertFalse(out["persistido"])
        self.assertFalse(out["publicacao_permitida"])
        print("SIDRA_INTERPERIODOS_REAL="+json.dumps({
            "status":out["status"],"periodos":out["periodos"],
            "n_capturas":out["n_capturas"],
            "por_periodo":out["por_periodo"],
            "persistido":out["persistido"],
            "homologado":out["observacoes_reais_homologadas"],
            "sem_persistencia":True
        },ensure_ascii=False,sort_keys=True),flush=True)
