import json
import unittest
from nivon.nasa_power_backfill import (
    planejar_backfill, diagnosticar_cache_backfill, ErroBackfillPower)
from nivon.grade_meteorologica_store import abrir_grade,ingerir_power_local

def plan(**kwargs):
    p=dict(latitude=-12.54,longitude=-55.72,
           desde="2024-12-30",ate="2025-01-02",
           parametros=("PRECTOTCORR",))
    p.update(kwargs)
    return planejar_backfill(**p)

def payload(p):
    from datetime import date,timedelta
    a=date.fromisoformat(p["inicio"])
    vals={}
    for i in range(p["intervalo_dias"]):
        vals[(a+timedelta(days=i)).strftime("%Y%m%d")]=float(i)
    return json.dumps({"geometry":{"coordinates":[-55.7,-12.5,400]},
                      "properties":{"parameter":{"PRECTOTCORR":vals}}}).encode()

class TestBackfillPower(unittest.TestCase):
    def setUp(self):
        self.db=abrir_grade()
        self.addCleanup(self.db.close)

    def test_janelas_anuais_separadas(self):
        p=plan()
        self.assertEqual(p["anos_incluidos"],2)
        self.assertEqual(p["dias_planejados"],4)
        self.assertEqual(p["planos"][0]["inicio"],"2024-12-30")
        self.assertEqual(p["planos"][0]["fim"],"2024-12-31")
        self.assertEqual(p["planos"][1]["inicio"],"2025-01-01")
        self.assertFalse(p["executar"])

    def test_ano_bissexto_suporta_366_dias(self):
        p=plan(desde="2024-01-01",ate="2024-12-31")
        self.assertEqual(p["dias_planejados"],366)
        self.assertEqual(p["planos"][0]["intervalo_dias"],366)

    def test_nao_aceita_1979_ou_2100(self):
        with self.assertRaises(ErroBackfillPower):
            plan(desde="1979-01-01",ate="2025-01-01")
        with self.assertRaises(ErroBackfillPower):
            plan(desde="2025-01-01",ate="2100-01-01")

    def test_backfill_detecta_cache_e_sem_data_publicacao(self):
        p=plan()
        diag=diagnosticar_cache_backfill(self.db,planejamento=p)
        self.assertEqual(diag["pendentes"],2)
        first=p["planos"][0]
        ingerir_power_local(self.db,bytes_json=payload(first),plano=first,
            coletado_em="2026-10-20T00:00:00Z")
        diag=diagnosticar_cache_backfill(self.db,planejamento=p)
        self.assertEqual(diag["pendentes"],1)
        self.assertEqual(diag["capturadas"],1)
        self.assertEqual(diag["janelas_detalhadas"][0]["estado"],
                         "CAPTURADO_PUBLICACAO_DESCONHECIDA")
        self.assertEqual(diag["janelas_detalhadas"][0]["armazenados"],2)

    def test_janelas_deduplicadas_identidade(self):
        p=plan()
        self.assertNotEqual(p["planos"][0]["consulta_sha256"],
                            p["planos"][1]["consulta_sha256"])
        self.assertEqual(plan()["planos"][0]["consulta_sha256"],
                         p["planos"][0]["consulta_sha256"])

if __name__=="__main__":unittest.main()
