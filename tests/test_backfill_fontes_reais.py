"""Planejamento do backfill histórico e isolamento por fonte, sem HTTP."""
import unittest
from scripts.backfill_fontes_reais import planejar_historico, backfill, ErroBackfill
from scripts.backfill_fontes_cloud import executar_historico


class BackfillTest(unittest.TestCase):
    def test_planos_segmentados_por_ano(self):
        plano=planejar_historico(fonte="BR_CCEE_PLD",inicio=2021,fim=2024)
        self.assertEqual(len(plano),4)
        self.assertEqual([p["ano"] for p in plano],[2021,2022,2023,2024])
        canada=planejar_historico(fonte="CAN_GRAINS_WEEKLY",inicio=2024,fim=2026)
        self.assertEqual([p["safra"] for p in canada],
                         ["2024-25","2025-26","2026-27"])

    def test_limites_historicos(self):
        with self.assertRaises(ErroBackfill):
            planejar_historico(fonte="BR_CCEE_PLD",inicio=2019,fim=2021)
        with self.assertRaises(ErroBackfill):
            planejar_historico(fonte="BR_CCEE_PLD",inicio=2021,fim=2030,max_anos=5)
        with self.assertRaises(ErroBackfill):
            planejar_historico(fonte="IBGE",inicio=2021,fim=2023)

    def test_default_deny_rede_e_cloud(self):
        res=backfill(fonte="CAN_GRAINS_WEEKLY",inicio=2025,fim=2026,
            banco="nao_criar.sqlite",raw_dir="nao_criar",executar=False)
        self.assertFalse(res["executado"])
        out=executar_historico(fonte="BR_CCEE_PLD",inicio=2023,fim=2024,
            projeto="nivon-data",dataset="agro",bucket="nivon-raw-archive",
            executar=False)
        self.assertEqual(out["modo"],"SIMULACAO_SEM_REDE")

if __name__=="__main__":
    unittest.main()
