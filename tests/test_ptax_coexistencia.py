"""Convivência do mesmo SHA PTAX legado e RAW sem modificar snapshots.

São fixtures SINTETICO em SQLite isolado, sem alegar coleta BCB real.
"""
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from nivon.captura_ptax_http import capturar_ptax_odata
from nivon.ptax_coexistencia import ErroCoexistenciaPTAX
from nivon.ptax_historico_decimal import (
    ErroHistoricoPTAX, selecionar_ptax_decimal_asof,
)
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.ptax_raw_sqlite import guardar_raw_ptax
from nivon.pipeline_api_dados import ingerir_json_local, observar_asof_coleta
from nivon.registro_snapshots import abrir_registro, ErroSnapshot

CAT = {"datasets":[{"id":"BCB_PTAX","source_id":"BCB"}]}
PLANO = planejar_consultas_ptax(
    moeda="USD", inicio="2026-10-19", fim="2026-10-20",
)[0]
T = datetime(2026,10,20,18,0,tzinfo=timezone.utc)
RAW = (b'{"value":[{"cotacaoCompra":5.10000,'
       b'"cotacaoVenda":5.12000,'
       b'"dataHoraCotacao":"2026-10-20 13:03:00"}]}')


def capturar(raw=RAW, when=T):
    return capturar_ptax_odata(
        PLANO, transporte=lambda url: (
            200, {"content-type":"application/json"}, raw,
        ), relogio=lambda:when,
    )


class TestCoexistenciaPTAX(unittest.TestCase):
    def setUp(self):
        self.db = abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def legado(self, raw=RAW, when=T):
        return ingerir_json_local(
            self.db, CAT, dataset_id="BCB_PTAX",
            payload=raw, plano=PLANO, coletado_em=when.isoformat(),
        )

    def novo(self, raw=RAW, when=T):
        return guardar_raw_ptax(self.db, CAT, capturar(raw,when))

    def resumo(self):
        return self.db.execute(
            "SELECT id,schema_versao,sha256,tipo FROM nivon_snapshots"
        ).fetchall()

    def test_mesmo_sha_legacy_antes_raw_adota_sem_duplicar_snapshot(self):
        self.legado()
        orig_id, schema, _, tipo = self.resumo()[0]
        self.assertEqual(schema,"PTAX_ODATA_1")
        r=self.novo()
        self.assertTrue(r["adotou_snapshot_legado"])
        self.assertEqual(r["schema_snapshot_preservado"],"PTAX_ODATA_1")
        self.assertFalse(r["nova_versao_snapshot"])
        self.assertEqual(len(self.resumo()),1)
        self.assertEqual(self.resumo()[0][0],orig_id)
        self.assertEqual(self.resumo()[0][1],schema)
        self.assertEqual(self.resumo()[0][3],tipo)
        count=self.db.execute(
            "SELECT COUNT(*) FROM nivon_observacoes_api").fetchone()[0]
        self.assertEqual(count,1)
        hist=selecionar_ptax_decimal_asof(
            self.db, corte=T.isoformat(), incluir_sinteticos=True)
        self.assertEqual(hist["status"],"PTAX_DECIMAL_ASOF_CONFERIDA_OFFLINE")
        self.assertEqual(hist["compra_decimal"],"5.10000")
        self.assertFalse(hist["publicavel"])

    def test_nova_coleta_mesmo_sha_reusa_schema_legado(self):
        self.legado()
        self.novo()
        r=self.novo(when=T+timedelta(hours=1))
        self.assertTrue(r["adotou_snapshot_legado"])
        self.assertTrue(r["nova_captura"])
        self.assertEqual(len(self.resumo()),1)
        count=self.db.execute(
            "SELECT COUNT(*) FROM nivon_coletas").fetchone()[0]
        self.assertEqual(count,2)

    def test_todos_os_registros_legados_devem_coincidir(self):
        self.legado()
        self.db.execute("UPDATE nivon_observacoes_api SET observacao_json='{}'")
        with self.assertRaisesRegex(ErroCoexistenciaPTAX,"corrompido"):
            self.novo()
        self.assertEqual(len(self.resumo()),1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_ptax_raw_capturas").fetchone()[0],0)

    def test_nao_adota_legado_sem_observacoes(self):
        self.legado()
        self.db.execute("DELETE FROM nivon_observacoes_api")
        with self.assertRaisesRegex(ErroCoexistenciaPTAX,"incompleto"):
            self.novo()

    def test_leitura_reconfere_normalizacao_legada(self):
        self.legado()
        self.novo()
        self.db.execute(
            "UPDATE nivon_observacoes_api SET observacao_json='{}'"
        )
        with self.assertRaisesRegex(ErroHistoricoPTAX,"legado divergente"):
            selecionar_ptax_decimal_asof(
                self.db,corte=T.isoformat(),incluir_sinteticos=True)

    def test_schema_desconhecido_nao_faz_migracao_automatica(self):
        self.legado()
        self.db.execute("UPDATE nivon_snapshots SET schema_versao='OUTRA_VERSAO'")
        with self.assertRaisesRegex(ErroCoexistenciaPTAX,"desconhecido"):
            self.novo()
        self.assertEqual(self.resumo()[0][1],"OUTRA_VERSAO")

    def test_direitos_ou_tipo_divergentes_bloqueiam(self):
        self.legado()
        self.db.execute(
            "UPDATE nivon_snapshots SET evidencia_direitos='FORJADO'"
        )
        with self.assertRaisesRegex(ErroCoexistenciaPTAX,"direitos"):
            self.novo()

    def test_fonte_incorreta_bloqueia(self):
        self.legado()
        self.db.execute(
            "UPDATE nivon_snapshots SET fonte_id='OUTRA'"
        )
        with self.assertRaisesRegex(ErroCoexistenciaPTAX,"metadados"):
            self.novo()

    def test_novo_sha_pode_coexistir_no_mesmo_banco_com_legado(self):
        self.legado()
        diferente=RAW.replace(b"5.10000",b"5.11000")
        novo=self.novo(diferente)
        self.assertFalse(novo["adotou_snapshot_legado"])
        self.assertTrue(novo["nova_versao_snapshot"])
        self.assertEqual(sorted(x[1] for x in self.resumo()),
                         ["PTAX_ODATA_1","PTAX_ODATA_RAW_V1"])
        hist=selecionar_ptax_decimal_asof(
            self.db,corte=T.isoformat(),incluir_sinteticos=True)
        self.assertEqual(hist["status"],"PTAX_DECIMAL_ASOF_CONFERIDA_OFFLINE")

    def test_raw_novo_antes_do_legado_nao_reescreve_schema(self):
        self.novo()
        with self.assertRaises(ErroSnapshot):
            self.legado()
        self.assertEqual(len(self.resumo()),1)
        self.assertEqual(self.resumo()[0][1],"PTAX_ODATA_RAW_V1")

    def test_savepoint_externo_volta_raw_sem_apagar_legado(self):
        self.legado()
        self.db.execute("SAVEPOINT externo")
        self.novo()
        self.db.execute("ROLLBACK TO SAVEPOINT externo")
        self.db.execute("RELEASE SAVEPOINT externo")
        self.assertEqual(len(self.resumo()),1)
        self.assertEqual(self.resumo()[0][1],"PTAX_ODATA_1")
        self.assertIsNone(self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='nivon_ptax_raw_blobs'").fetchone())

    def test_persistencia_legada_continua_consultavel(self):
        self.legado()
        self.novo()
        dados=observar_asof_coleta(
            self.db, dataset_id="BCB_PTAX",
            corte_coleta=T.isoformat(),incluir_sinteticos=True,
        )
        self.assertEqual(dados["linhas"],1)
        self.assertEqual(dados["registros"][0]["observacao"]
                         ["cotacao_compra_brl_por_moeda"],5.1)


if __name__=="__main__":
    unittest.main()
