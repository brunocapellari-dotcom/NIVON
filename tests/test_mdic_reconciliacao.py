import tempfile
import unittest
from pathlib import Path
from nivon.mdic_reconciliacao import reconciliar_totais_mdic,ErroReconciliacaoMDIC
from nivon.mdic_stream import processar_arquivo_anual
from nivon.mdic_exportacao import HEADER
URL="https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta"

def base():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"EXP_2026.csv"
        campos=dict(CO_ANO="2026",CO_MES="09",CO_NCM="12019000",CO_UNID="10",
                    CO_PAIS="160",SG_UF_NCM="MT",CO_VIA="01",CO_URF="081",
                    QT_ESTAT="1",KG_LIQUIDO="2000",VL_FOB="800")
        p.write_text(";".join(HEADER)+"\n"+";".join(campos[k] for k in HEADER)+"\n")
        return processar_arquivo_anual(p,ano=2026,direcao="EXPORTACAO",granularidade="NCM",
                  codigos=frozenset({"12019000"}),coletado_em="2026-10-19T18:00:00Z")
def ref(**kwargs):
    row={"competencia":"2026-09","kg":2000,"fob_usd":800}
    row.update(kwargs)
    return [row]
class TestReconciliacao(unittest.TestCase):
    def test_exact_match_not_homologation(self):
        out=reconciliar_totais_mdic(base(),referencias=ref(),fonte_referencia=URL)
        self.assertEqual(out["resultado"],"TOTAIS_CONFERIDOS_ARITMETICAMENTE")
        self.assertEqual((out["peso_total_kg"],out["fob_total_usd"]),(2000,800))
        self.assertFalse(out["publicacao_comercial_autorizada"])
    def test_mismatch_kg_fail(self):
        with self.assertRaises(ErroReconciliacaoMDIC):
            reconciliar_totais_mdic(base(),referencias=ref(kg=2001),fonte_referencia=URL)
    def test_mismatch_fob_fail(self):
        with self.assertRaises(ErroReconciliacaoMDIC):
            reconciliar_totais_mdic(base(),referencias=ref(fob_usd=999),fonte_referencia=URL)
    def test_zero_total_reference_is_not_automatic(self):
        with self.assertRaises(ErroReconciliacaoMDIC):
            reconciliar_totais_mdic(base(),referencias=ref(kg=0),fonte_referencia=URL)
    def test_missing_month_rejected(self):
        with self.assertRaises(ErroReconciliacaoMDIC):
            reconciliar_totais_mdic(base(),referencias=[{"competencia":"2026-08","kg":2000,"fob_usd":800}],fonte_referencia=URL)
    def test_bad_source_rejected(self):
        with self.assertRaises(ErroReconciliacaoMDIC):
            reconciliar_totais_mdic(base(),referencias=ref(),fonte_referencia="https://fake.example/")
    def test_duplicate_reference_rejected(self):
        with self.assertRaises(ErroReconciliacaoMDIC):
            reconciliar_totais_mdic(base(),referencias=ref()+ref(),fonte_referencia=URL)
    def test_forgot_a_row_detected(self):
        r=base();r["totais_arquivo_por_mes"][0]["linhas"]=0
        with self.assertRaises(ErroReconciliacaoMDIC):
            reconciliar_totais_mdic(r,referencias=ref(),fonte_referencia=URL)
    def test_large_tolerance_rejected(self):
        with self.assertRaises(ErroReconciliacaoMDIC):
            reconciliar_totais_mdic(base(),referencias=ref(),fonte_referencia=URL,tolerancia_kg=10_000)
