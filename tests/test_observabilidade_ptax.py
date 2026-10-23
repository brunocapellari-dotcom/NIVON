"""Alertas locais PTAX (coleta, não validação de cotação ou SLA de bolsa)."""
import json
import unittest

from nivon.pipeline_api_dados import abrir_registro, ingerir_json_local
from nivon.observabilidade_local import monitorar_operacao
from nivon.ptax_plano import planejar_consultas_ptax

CAT={"datasets":[{"id":"BCB_PTAX","source_id":"BCB",
                  "enabled":True,"collection_authorized":True}]}
PLAN=planejar_consultas_ptax(moeda="USD",inicio="2026-10-01",fim="2026-10-02")[0]
BODY=json.dumps({"value":[{
    "cotacaoCompra":5.1,"cotacaoVenda":5.11,
    "dataHoraCotacao":"2026-10-01 13:03:00",
}]}).encode()


class TestPTAXMonitor(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")

    def tearDown(self):
        self.db.close()

    def monitorar(self):
        return monitorar_operacao(
            gerado_em="2026-10-20T15:00:00+00:00",mercados=self.db)

    def ingerir(self,*,coleta="2026-10-19T12:00:00+00:00",tipo="REAL_AUTORIZADO"):
        return ingerir_json_local(
            self.db,CAT,payload=BODY,dataset_id="BCB_PTAX",
            plano=PLAN,coletado_em=coleta,tipo=tipo,
            autorizacoes=(frozenset({"COLETA","ARMAZENAMENTO"})
                          if tipo=="REAL_AUTORIZADO" else frozenset()),
            evidencia_direitos=("MOCK_TESTE" if tipo=="REAL_AUTORIZADO" else None),
        )

    def test_sem_banco_de_mercado_cobertura_parcial(self):
        r=monitorar_operacao(gerado_em="2026-10-20T15:00:00+00:00")
        self.assertEqual(r["cobertura"]["ptax"],"NAO_CONFIGURADO")

    def test_sem_captura_real_gera_alerta(self):
        r=self.monitorar()
        self.assertIn("PTAX_SEM_COLETA_REAL",
                      {a["codigo"] for a in r["alertas"]})

    def test_sintetico_nao_conta_como_captura_real(self):
        self.ingerir(tipo="SINTETICO")
        r=self.monitorar()
        self.assertIn("PTAX_SEM_COLETA_REAL",
                      {a["codigo"] for a in r["alertas"]})

    def test_captura_recente_real_no_alerta_de_atraso(self):
        self.ingerir()
        r=self.monitorar()
        self.assertNotIn("PTAX_COLETA_ATRASADA",
                         {a["codigo"] for a in r["alertas"]})
        self.assertEqual(r["cobertura"]["ptax"],"CONSULTADO")

    def test_captura_antiga_gera_alerta(self):
        self.ingerir(coleta="2026-10-05T12:00:00+00:00")
        r=self.monitorar()
        self.assertIn("PTAX_COLETA_ATRASADA",
                      {a["codigo"] for a in r["alertas"]})

    def test_coleta_no_futuro_rejeitada_no_monitor(self):
        self.ingerir(coleta="2026-10-21T12:00:00+00:00")
        r=self.monitorar()
        self.assertIn("PTAX_COLETA_FUTURA",
                      {a["codigo"] for a in r["alertas"]})


if __name__=="__main__":
    unittest.main()
