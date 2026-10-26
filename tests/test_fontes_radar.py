import copy
import unittest
from nivon.fontes_radar import radar

NOW="2026-10-25T20:30:00+00:00"
EVENT={"fonte":"ANTT","evento_id":"fixture-sha-a","estado":"NORMALIZED",
       "data_referencia":"2026-08-01","competencia":"2026-08",
       "data_publicacao":None,"data_coleta":NOW}
POLICY={"ANTT":{"homologada":True,"limite_defasagem_dias":100,"intervalo_coleta_minutos":1440}}


class TestRadar(unittest.TestCase):
    def item(self,events=None,policy=None):
        return radar([copy.deepcopy(EVENT)] if events is None else events,
                     POLICY if policy is None else policy,agora=NOW)["fontes"][0]

    def test_fresh_nao_significa_homologacao_e_preserva_tempos(self):
        row=self.item()
        self.assertEqual(row["estado"],"fresh")
        self.assertEqual(row["data_referencia"],"2026-08-01")
        self.assertEqual(row["data_coleta"],NOW)
        self.assertIsNone(row["data_publicacao"])
        self.assertFalse(row["promocao_autorizada"])

    def test_coleta_recente_nao_rejuvenesce_referencia(self):
        event=dict(EVENT,data_referencia="2025-08-01",competencia="2025-08")
        self.assertEqual(self.item([event])["estado"],"lagged")

    def test_duplicado_identico_idempotente_divergente_indisponivel(self):
        self.assertEqual(self.item([EVENT,copy.deepcopy(EVENT)]),self.item([EVENT]))
        other=dict(EVENT,data_referencia="2026-07-01",competencia="2026-07")
        self.assertEqual(self.item([EVENT,other])["estado"],"unavailable")

    def test_revisao_mesma_referencia_nao_vira_dado_novo(self):
        old=dict(EVENT,evento_id="older",data_coleta="2026-10-24T20:30:00+00:00")
        row=self.item([old,EVENT])
        self.assertTrue(row["revisao_detectada"])
        self.assertEqual(row["data_referencia"],"2026-08-01")

    def test_fonte_quebrada_e_recuperacao(self):
        old=dict(EVENT,evento_id="old-event",data_coleta="2026-10-23T20:30:00+00:00")
        failure={"fonte":"ANTT","evento_id":"failure","estado":"UNAVAILABLE","data_coleta":"2026-10-24T20:30:00+00:00"}
        self.assertEqual(self.item([old,failure])["estado"],"unavailable")
        self.assertEqual(self.item([old,failure,EVENT])["estado"],"fresh")

    def test_coletor_antigo_nao_e_saude_fresh(self):
        event=dict(EVENT,data_coleta="2026-09-01T20:30:00+00:00")
        self.assertEqual(self.item([event])["estado"],"unavailable")

    def test_quarentena_e_fonte_sem_homologacao_nao_promovidas(self):
        self.assertEqual(self.item([dict(EVENT,estado="QUARANTINED")])["estado"],"quarantined")
        policy=copy.deepcopy(POLICY);policy["ANTT"]["homologada"]=False
        self.assertEqual(self.item(policy=policy)["estado"],"quarantined")
        self.assertEqual(self.item(policy={})["estado"],"quarantined")

    def test_ausencia_fica_null_nunca_zero(self):
        row=self.item([])
        self.assertEqual(row["estado"],"unavailable")
        self.assertIsNone(row["eventos_distintos"])
        self.assertIsNone(row["data_referencia"])

    def test_metadados_futuros_fuso_e_politica_invalidos(self):
        for field,value in (("data_coleta","2026-10-26T20:30:00+00:00"),
                            ("data_coleta","2026-10-25T20:30:00"),
                            ("data_publicacao","2026-11-01"),
                            ("competencia","2026-07")):
            self.assertEqual(self.item([dict(EVENT,**{field:value})])["estado"],"unavailable")
        policy=copy.deepcopy(POLICY);policy["ANTT"]["limite_defasagem_dias"]=float('nan')
        self.assertEqual(self.item(policy=policy)["estado"],"unavailable")

    def test_agro_sem_referencia_permanece_quarentena(self):
        events=[{"fonte":fonte,"evento_id":"fixture","estado":"QUARANTINED","data_coleta":NOW}
                for fonte in ("CEPEA","IMEA","CONAB")]
        report=radar(events,{},agora=NOW)
        self.assertEqual([x["estado"] for x in report["fontes"]],["unavailable","quarantined","quarantined","quarantined"])
        self.assertEqual(report["consultas_sql"],0)
        self.assertEqual(report["coletas"],0)


if __name__=='__main__':unittest.main()
