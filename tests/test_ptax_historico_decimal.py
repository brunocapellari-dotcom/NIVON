"""Comparação temporal PTAX Decimal (fixtures, sem BCB ao vivo)."""
import sqlite3
import unittest
from datetime import datetime, timezone, timedelta

from nivon.captura_ptax_http import capturar_ptax_odata
from nivon.ptax_historico_decimal import (
    ErroHistoricoPTAX, selecionar_ptax_decimal_asof,
    indicador_ptax_decimal_raw,
)
from nivon.ptax_raw_sqlite import guardar_raw_ptax
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.registro_snapshots import abrir_registro

CAT={"datasets":[{"id":"BCB_PTAX","source_id":"BCB"}]}
PLAN=planejar_consultas_ptax(
    moeda="USD",inicio="2026-10-19",fim="2026-10-20")[0]
T=datetime(2026,10,20,18,0,tzinfo=timezone.utc)
RIGHTS={"BCB_PTAX":{"status_direitos":"APROVADA",
                    "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]}}


def body(preco="5.10000", *, dia="2026-10-20", tipo=None):
    extra=(',"tipoBoletim":"'+tipo+'"') if tipo else ""
    return ('{"value":[{"cotacaoCompra":'+preco+
            ',"cotacaoVenda":5.12000,"dataHoraCotacao":"'+
            dia+' 13:03:00"'+extra+'}]}').encode()


def captura(raw, instante=T):
    return capturar_ptax_odata(
        PLAN,transporte=lambda _: (
            200,{"content-type":"application/json",
                 "content-length":str(len(raw))},raw),
        relogio=lambda:instante)


class TestPTAXHistoricoDecimal(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def add(self,raw,at=T):
        return guardar_raw_ptax(self.db,CAT,captura(raw,at))

    def consultar(self,**kw):
        opcoes={"incluir_sinteticos":True,**kw}
        return selecionar_ptax_decimal_asof(
            self.db,corte=(T+timedelta(hours=2)).isoformat(),**opcoes)

    def test_decimal_exato_no_historico(self):
        self.add(body())
        r=self.consultar()
        self.assertEqual(r["compra_decimal"],"5.10000")
        self.assertEqual(r["compra_dec4"],"5.1000")
        self.assertEqual(r["venda_dec4"],"5.1200")
        self.assertEqual(r["tipo_selecionado"],
                         "BOLETIM_SEM_FECHAMENTO_COMPROVADO")
        self.assertEqual(r["ponteiro_json"],"/value/0")
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["publicacao_oficial_comprovada"])

    def test_sem_classe_real_padrão(self):
        self.add(body())
        status=selecionar_ptax_decimal_asof(
            self.db,corte=T.isoformat())
        self.assertEqual(status["status"],"SEM_RAW_PTAX_ATE_CORTE")
        self.assertEqual(indicador_ptax_decimal_raw(
            self.db,gerado_em=T.isoformat(),fontes=RIGHTS)["status"],
            "SEM_RAW_PTAX_ATE_CORTE")

    def test_preview_bloqueada_sem_direitos(self):
        self.add(body())
        r=indicador_ptax_decimal_raw(
            self.db,gerado_em=T.isoformat(),fontes={})
        self.assertEqual(r["status"],"BLOQUEADO_DIREITOS")
        self.assertNotIn("indicador",r)

    def test_recaptura_identica_nao_cria_nova_taxa(self):
        self.add(body())
        self.add(body(),T+timedelta(hours=1))
        r=self.consultar()
        self.assertEqual(r["total_capturas"],2)
        self.assertEqual(r["total_boletins_unicos"],1)
        self.assertEqual(r["primeira_coleta_conhecida"],T.isoformat())

    def test_documento_mais_novo_com_boletim_mais_antigo_nao_perde_recente(self):
        self.add(body())
        self.add(body(preco="5.05000",dia="2026-10-19"),
                 T+timedelta(hours=1))
        r=self.consultar()
        self.assertEqual(r["compra_decimal"],"5.10000")
        self.assertEqual(r["total_boletins_unicos"],2)

    def test_versoes_conflitantes_mesmo_boletim_bloqueadas(self):
        self.add(body(preco="5.10000"))
        self.add(body(preco="5.11000"),T+timedelta(hours=1))
        r=self.consultar()
        self.assertEqual(r["status"],"VINTAGES_CONFLITANTES")
        self.assertFalse(r["apto_backtest_por_publicacao"])

    def test_fechamento_so_quando_explicito(self):
        self.add(body(tipo="Fechamento"))
        r=self.consultar(somente_fechamento=True)
        self.assertEqual(r["tipo_selecionado"],"FECHAMENTO")
        self.assertEqual(r["tipo_boletim"],"Fechamento")
        self.assertNotIn("publicacao_oficial_em",r)

    def test_fechamento_nao_inferido(self):
        self.add(body())
        r=self.consultar(somente_fechamento=True)
        self.assertEqual(r["status"],"SEM_FECHAMENTO_EXPLICITO")

    def test_boletim_vencido_bloqueado(self):
        self.add(body(dia="2026-10-19"))
        r=self.consultar(idade_maxima_horas=4)
        self.assertEqual(r["status"],"DADO_PTAX_VENCIDO")

    def test_historico_e_corte_anterior(self):
        self.add(body())
        self.add(body(dia="2026-10-19",preco="5.04000"),
                 T+timedelta(hours=1))
        r=selecionar_ptax_decimal_asof(
            self.db,corte=T.isoformat(),incluir_sinteticos=True)
        self.assertEqual(r["total_capturas"],1)
        self.assertEqual(r["compra_decimal"],"5.10000")

    def test_adulteracao_raw_detectada(self):
        self.add(body())
        self.db.execute("UPDATE nivon_ptax_raw_blobs SET dados=?",
                        (b"not-original",))
        with self.assertRaisesRegex(ErroHistoricoPTAX,"divergentes"):
            self.consultar()

    def test_snapshot_trocado_de_tipo_no_banco_nao_aparece(self):
        self.add(body())
        self.db.execute("UPDATE nivon_ptax_raw_capturas SET tipo='REAL_AUTORIZADO'")
        r=selecionar_ptax_decimal_asof(
            self.db,corte=T.isoformat())
        self.assertEqual(r["status"],"SEM_RAW_PTAX_ATE_CORTE")

    def test_sem_tabelas_somente_leitura(self):
        db=sqlite3.connect(":memory:")
        try:
            r=selecionar_ptax_decimal_asof(db,corte=T.isoformat())
            self.assertEqual(r["status"],"RAW_PTAX_INDISPONIVEL")
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0],0)
        finally:
            db.close()

    def test_parametros_invalidos(self):
        self.add(body())
        for opts in ({"moeda":"JPY"},{"incluir_sinteticos":"sim"},
                     {"somente_fechamento":1},{"idade_maxima_horas":0}):
            with self.subTest(opts=opts),self.assertRaises(ErroHistoricoPTAX):
                self.consultar(**opts)

    def test_previa_nao_promove_fixture(self):
        self.add(body(tipo="Fechamento"))
        r=indicador_ptax_decimal_raw(
            self.db,gerado_em=(T+timedelta(hours=1)).isoformat(),
            fontes=RIGHTS)
        self.assertEqual(r["status"],"SEM_RAW_PTAX_ATE_CORTE")
        self.assertNotIn("indicador",r)


if __name__=="__main__":
    unittest.main()
