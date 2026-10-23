"""Ensaios ponta-a-ponta de continuidade PTAX: ingestão, adoção, backup,
restauração, auditoria e reversão por cópia. Nenhum GET real ou deploy.
"""
import copy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import sqlite3
import unittest

from nivon.continuidade_ptax import (
    ErroContinuidadePTAX, auditar_integridade_ptax,
    planejar_migracao_ptax, criar_pacote_backup_ptax,
    restaurar_pacote_backup_ptax,
)
from nivon.pipeline_api_dados import ingerir_json_local, observar_asof_coleta
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.ptax_raw_sqlite import guardar_raw_ptax, consultar_raw_ptax_asof
from nivon.ptax_historico_decimal import selecionar_ptax_decimal_asof
from nivon.registro_snapshots import abrir_registro
from nivon.captura_ptax_http import capturar_ptax_odata

CAT = {"datasets":[{"id":"BCB_PTAX","source_id":"BCB"}]}
PLANO = planejar_consultas_ptax(
    moeda="USD",inicio="2026-10-19",fim="2026-10-20",
)[0]
T = datetime(2026,10,20,18,0,tzinfo=timezone.utc)
RAW = (b'{"value":[{"cotacaoCompra":5.10000,"cotacaoVenda":5.12000,'
       b'"dataHoraCotacao":"2026-10-20 13:03:00"}]}')


def captura(raw=RAW, instante=T):
    return capturar_ptax_odata(
        PLANO, transporte=lambda _: (
            200,{"content-type":"application/json"},raw,
        ), relogio=lambda:instante,
    )


class TestContinuidadePTAX(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def legado(self, raw=RAW):
        return ingerir_json_local(
            self.db,CAT,payload=raw,dataset_id="BCB_PTAX",
            plano=PLANO,coletado_em=T.isoformat(),
        )

    def armazenar(self,raw=RAW,instante=T):
        return guardar_raw_ptax(self.db,CAT,captura(raw,instante))

    def backup(self):
        # Snapshot é consistente quando não há transação pendente.
        self.db.commit()
        return criar_pacote_backup_ptax(self.db)

    def test_integracao_completa_ingestao_raw_ledger_backup_restore_asof(self):
        self.legado()
        self.armazenar()
        self.armazenar(instante=T+timedelta(hours=1))
        pre=auditar_integridade_ptax(self.db)
        self.assertEqual(pre["total_snapshots"],1)
        self.assertEqual(pre["total_capturas_raw"],2)
        self.assertEqual(pre["legados_sem_raw"],0)
        self.assertEqual(pre["schemas"]["PTAX_ODATA_1"],1)
        self.assertFalse(pre["publicavel"])
        plano=planejar_migracao_ptax(self.db)
        self.assertEqual(plano["estado"],"RAW_DISPONIVEIS_LOCALMENTE")
        self.assertFalse(plano["migracao_automatica_autorizada"])
        pacote=self.backup()
        self.assertEqual(pacote["manifesto"]["sha256"],
                         sha256(pacote["sqlite_bytes"]).hexdigest())
        restaurado=restaurar_pacote_backup_ptax(pacote)
        self.addCleanup(restaurado.close)
        self.assertEqual(auditar_integridade_ptax(restaurado),pre)
        storico=selecionar_ptax_decimal_asof(
            restaurado,corte=(T+timedelta(hours=2)).isoformat(),
            incluir_sinteticos=True,
        )
        self.assertEqual(storico["compra_decimal"],"5.10000")
        self.assertEqual(storico["total_capturas"],2)
        legado=observar_asof_coleta(
            restaurado,dataset_id="BCB_PTAX",
            corte_coleta=T.isoformat(),incluir_sinteticos=True,
        )
        self.assertEqual(legado["registros"][0]["observacao"]
                         ["cotacao_compra_brl_por_moeda"],5.1)
        raw=consultar_raw_ptax_asof(
            restaurado,corte=T.isoformat(),incluir_sinteticos=True)
        self.assertEqual(raw["schema_snapshot_preservado"],"PTAX_ODATA_1")
        self.assertEqual(raw["boletins"][0]["cotacao_venda_decimal"],"5.12000")

    def test_recuperacao_depois_de_corrupcao_da_origem(self):
        self.legado()
        self.armazenar()
        pacote=self.backup()
        self.db.execute("UPDATE nivon_ptax_raw_blobs SET dados=?",(b"INVALID",))
        with self.assertRaisesRegex(ErroContinuidadePTAX,"adulterados"):
            auditar_integridade_ptax(self.db)
        reparado=restaurar_pacote_backup_ptax(pacote)
        self.addCleanup(reparado.close)
        self.assertEqual(auditar_integridade_ptax(reparado)["total_capturas_raw"],1)
        self.assertEqual(reparado.execute(
            "SELECT dados FROM nivon_ptax_raw_blobs").fetchone()[0],RAW)
        # A restauração não altera a origem corrompida.
        self.assertEqual(self.db.execute(
            "SELECT dados FROM nivon_ptax_raw_blobs").fetchone()[0],b"INVALID")

    def test_manifesto_ou_payload_adulterado_falha_fechado(self):
        self.armazenar()
        pacote=self.backup()
        for variant in (
            {**pacote,"sqlite_bytes":pacote["sqlite_bytes"][:-1]+b"Z"},
            {"sqlite_bytes":pacote["sqlite_bytes"],
             "manifesto":{**pacote["manifesto"],"bytes":1}},
            {"sqlite_bytes":pacote["sqlite_bytes"],
             "manifesto":{**pacote["manifesto"],"inventario":{
                **pacote["manifesto"]["inventario"],"total_capturas_raw":999}}},
        ):
            with self.subTest(variant=variant["manifesto"]["bytes"]),self.assertRaises(ErroContinuidadePTAX):
                clone=restaurar_pacote_backup_ptax(variant)
                clone.close()

    def test_snapshot_legado_sem_bytes_nao_vira_raw_falso(self):
        self.legado()
        result=planejar_migracao_ptax(self.db)
        self.assertEqual(result["estado"],"AGUARDAR_DOCUMENTOS_ORIGINAIS")
        self.assertEqual(result["documentos_a_recuperar"],1)
        self.assertEqual(len(result["sha_sem_raw"]),1)
        self.assertFalse(result["migracao_automatica_autorizada"])
        pacote=self.backup()
        rec=restaurar_pacote_backup_ptax(pacote)
        self.addCleanup(rec.close)
        self.assertEqual(planejar_migracao_ptax(rec)["documentos_a_recuperar"],1)

    def test_raw_novo_sem_legado_backupeado_corretamente(self):
        self.armazenar()
        p=self.backup()
        clone=restaurar_pacote_backup_ptax(p)
        self.addCleanup(clone.close)
        self.assertEqual(
            planejar_migracao_ptax(clone)["schema"]["PTAX_ODATA_RAW_V1"],1)
        self.assertEqual(
            selecionar_ptax_decimal_asof(clone,corte=T.isoformat(),
                                         incluir_sinteticos=True)["compra_decimal"],
            "5.10000")
        self.assertEqual(
            observar_asof_coleta(clone,dataset_id="BCB_PTAX",
                                 corte_coleta=T.isoformat(),
                                 incluir_sinteticos=True)["linhas"],0)

    def test_backup_recusa_transacao_aberta(self):
        self.armazenar()
        with self.assertRaisesRegex(ErroContinuidadePTAX,"transação aberta"):
            criar_pacote_backup_ptax(self.db)

    def test_integridade_detecta_blobs_orfaos(self):
        self.armazenar()
        self.db.execute(
            "INSERT INTO nivon_ptax_raw_blobs(sha256,dados,bytes) VALUES(?,?,?)",
            (sha256(b"orfao").hexdigest(),b"orfao",5),
        )
        with self.assertRaisesRegex(ErroContinuidadePTAX,"sem captura"):
            auditar_integridade_ptax(self.db)

    def test_integridade_detecta_vinculo_coleta_adulterado(self):
        self.armazenar()
        self.db.execute("DELETE FROM nivon_coletas")
        with self.assertRaisesRegex(ErroContinuidadePTAX,"sem coleta"):
            auditar_integridade_ptax(self.db)

    def test_integridade_detecta_legado_corrompido(self):
        self.legado()
        self.armazenar()
        self.db.execute("UPDATE nivon_observacoes_api SET observacao_json='{}'")
        with self.assertRaisesRegex(ErroContinuidadePTAX,"parser ou observações"):
            auditar_integridade_ptax(self.db)

    def test_erro_ao_restaurar_sem_esquema_ou_sqlite_bytes(self):
        with self.assertRaises(ErroContinuidadePTAX):
            restaurar_pacote_backup_ptax({"manifesto":{},"sqlite_bytes":b""})
        with self.assertRaises(ErroContinuidadePTAX):
            auditar_integridade_ptax(sqlite3.connect(":memory:"))

    def test_backup_readonly_nao_autoriza_envio(self):
        self.armazenar()
        self.db.commit()
        rows=self.db.execute("SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0]
        pacote=criar_pacote_backup_ptax(self.db)
        self.assertFalse(pacote["publicavel"])
        self.assertFalse(pacote["manifesto"]["backup_externo_immutavel"])
        self.assertFalse(pacote["manifesto"]["tempo_confiavel_independente"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],rows)


if __name__=="__main__":
    unittest.main()
