"""Execução em lote PTAX com rollback e restauração E2E (fixtures)."""
from datetime import datetime, timezone
import sqlite3
import unittest

from nivon.orquestracao_ptax_lote import executar_lote_ptax, ErroLotePTAX
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.registro_snapshots import abrir_registro
from nivon.continuidade_ptax import (
    criar_pacote_backup_ptax, restaurar_pacote_backup_ptax,
)
from nivon.ptax_historico_decimal import selecionar_ptax_decimal_asof

CAT={"datasets":[{"id":"BCB_PTAX","source_id":"BCB"}]}
P1=planejar_consultas_ptax(moeda="USD",
                           inicio="2026-10-19",fim="2026-10-19")[0]
P2=planejar_consultas_ptax(moeda="USD",
                           inicio="2026-10-20",fim="2026-10-20")[0]
T=datetime(2026,10,21,12,0,tzinfo=timezone.utc)


def resposta(url):
    data="2026-10-19" if url == P1["url"] else "2026-10-20"
    preco="5.1000" if data.endswith("19") else "5.2000"
    raw=('{"value":[{"cotacaoCompra":'+preco+
         ',"cotacaoVenda":5.2200,'
         '"dataHoraCotacao":"'+data+' 13:03:00"}]}').encode()
    return 200,{"content-type":"application/json",
                "content-length":str(len(raw))},raw


def rodar(db,planos=None,transport=resposta,**kwargs):
    return executar_lote_ptax(
        db,CAT,planos=planos if planos is not None else [P1,P2],
        transporte_injetado=transport,relogio=lambda:T,**kwargs,
    )


class TestOrquestracaoPTAXLote(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def test_ingestao_duas_janelas_backup_restore_historico(self):
        r=rodar(self.db)
        self.assertEqual(r["consultas_concluidas"],2)
        self.assertEqual(r["boletins_processados"],2)
        self.assertEqual(r["tipo"],"SINTETICO")
        self.assertFalse(r["rede_ativada_por_este_comando"])
        self.assertFalse(r["publicavel"])
        self.assertEqual(r["inventario"]["total_capturas_raw"],2)
        self.assertEqual(r["inventario"]["total_snapshots"],2)
        self.db.commit()
        b=criar_pacote_backup_ptax(self.db)
        d=restaurar_pacote_backup_ptax(b)
        self.addCleanup(d.close)
        historico=selecionar_ptax_decimal_asof(
            d,corte=T.isoformat(),incluir_sinteticos=True,
        )
        self.assertEqual(historico["compra_decimal"],"5.2000")
        self.assertEqual(historico["total_boletins_unicos"],2)

    def test_lote_repetido_nao_duplica_snapshot(self):
        rodar(self.db)
        r=rodar(self.db)
        self.assertTrue(all(not x["nova_captura"] for x in r["resultados"]))
        self.assertEqual(r["inventario"]["total_capturas_raw"],2)

    def test_segunda_janela_falha_e_tudo_rollback_inclusive_ddl(self):
        def corruptor(url):
            if url==P2["url"]:
                return 200,{"content-type":"text/html"},b"<html>denied</html>"
            return resposta(url)
        with self.assertRaises(Exception):
            rodar(self.db,transport=corruptor)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)
        self.assertIsNone(self.db.execute(
            "SELECT name FROM sqlite_master WHERE name='nivon_ptax_raw_blobs'"
        ).fetchone())

    def test_componente_pode_integrar_sempre_na_mesma_transacao_externa(self):
        self.db.execute("SAVEPOINT externo")
        rodar(self.db)
        self.db.execute("ROLLBACK TO SAVEPOINT externo")
        self.db.execute("RELEASE SAVEPOINT externo")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_sem_rede_por_padrao_ou_permissao_inventada(self):
        with self.assertRaises(PermissionError):
            executar_lote_ptax(self.db,CAT,planos=[P1])
        with self.assertRaises(ErroLotePTAX):
            rodar(self.db,autorizacoes=frozenset({"COLETA"}))
        with self.assertRaises(ErroLotePTAX):
            rodar(self.db,permitir_rede=True)

    def test_nao_reprocessa_mesma_janela_duas_vezes_no_lote(self):
        with self.assertRaisesRegex(ErroLotePTAX,"duplicada"):
            rodar(self.db,planos=[P1,P1])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_plano_adulterado_e_lote_excessivo_bloqueados_antes_do_io(self):
        for planos in ([],[P1]*21,[{**P1,"url":"https://example.org"}],
                       [{**P1,"inicio":"2026-10-18"}]):
            with self.subTest(p=planos[:1]),self.assertRaises(ErroLotePTAX):
                rodar(self.db,planos=planos)

    def test_etapa_gera_inventario_sem_publicacao(self):
        r=rodar(self.db,planos=[P2])
        self.assertFalse(r["registro_de_publicacao_comprovado"])
        self.assertFalse(r["apto_backtest_por_publicacao"])
        self.assertEqual(len(r["resultados"]),1)
        self.assertEqual(r["inventario"]["legados_sem_raw"],0)


if __name__=="__main__":
    unittest.main()
