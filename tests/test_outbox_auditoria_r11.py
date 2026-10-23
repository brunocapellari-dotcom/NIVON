"""R11: testam o relatório de anomalias e concorrência/recuperação entre processos."""
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.auditoria_outbox_integrada import auditar_integridade_envios
from nivon.backup_outbox import verificar_backup, estado_logico
from nivon.migracao_outbox_legada import (
    hash_snapshot_legado, registrar_quarentena,
)
from nivon.outbox_briefing import (
    abrir_outbox, agendar_briefing, reservar_para_entrega,
    registrar_aceite, confirmar_entrega,
)
from nivon.outbox_unificada import (
    ErroControleEnvio, mensagem_de_prova, registrar_decisao_consentimento,
)
from nivon.outbox_whatsapp import _esquema as whatsapp_esquema

SECRET=b"TEST-R11-AUDITORIA-CONSENTIMENTO-SIMULADO-NAO-PRODUCAO-00000"
AGORA="2026-10-23T12:00:00+00:00"
DIA="2026-10-23"
HASH="a"*64


def consentir(con):
    prov="OPTIN-R11-FIXTURE-SINTETICA"
    value=mensagem_de_prova(
        acao="CONCEDER",destinatario_hmac=HASH,evidencia_id=prov,em=AGORA,
    )
    registrar_decisao_consentimento(
        con,acao="CONCEDER",destinatario_hmac=HASH,evidencia_id=prov,
        em=AGORA,assinatura=hmac.new(SECRET,value,hashlib.sha256).hexdigest(),
        chave_verificacao=SECRET,
    )


def preparar_briefing(con, destino=HASH):
    text="Briefing sintético para validar trilha de evidências e recuperação."
    return agendar_briefing(
        con,dia_local=DIA,destinatario_hmac=destino,
        briefing={"status":"PREPARADO_SEM_ENVIO","texto":text,
                  "sha256":hashlib.sha256(text.encode()).hexdigest()},
        agora=AGORA,auditoria_aprovada=True,
    )


class TestAuditoriaOutboxR11(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.path=Path(self.tmp.name)/"outbox.sqlite"
        self.con=abrir_outbox(self.path)
        consentir(self.con)
        whatsapp_esquema(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def entregue(self):
        i=preparar_briefing(self.con)["id"]
        reserva=reservar_para_entrega(self.con,id=i)
        registrar_aceite(
            self.con,id=i,token=reserva["token"],
            provider_message_id="wamid.r11.synthetic",
        )
        confirmar_entrega(
            self.con,provider_message_id="wamid.r11.synthetic",
            autenticado=True,quando=AGORA,
        )
        return i

    def test_ledger_consistente_e_resultado_sem_pii(self):
        self.entregue()
        snap=estado_logico(self.con)
        report=auditar_integridade_envios(self.con)
        self.assertEqual(report["situacao"],"SEM_DIVERGENCIAS_ESTRUTURAIS")
        self.assertEqual(report["total_anomalias"],0)
        self.assertEqual(report["contagens"]["reservas"],1)
        self.assertEqual(report["contagens"]["recibos"],1)
        self.assertTrue(report["somente_leitura"])
        self.assertFalse(report["homologacao_externa_verificada"])
        self.assertEqual(snap,estado_logico(self.con))
        self.assertNotIn(HASH,json.dumps(report))
        self.assertNotIn("wamid.r11.synthetic",json.dumps(report))

    def test_entrega_legacy_adulterada_revelada_sem_promover(self):
        self.entregue()
        self.con.execute("UPDATE briefing_outbox SET status='ACCEPTED' WHERE id=1")
        self.con.commit()
        report=auditar_integridade_envios(self.con)
        self.assertEqual(report["anomalias"]["ESTADO_LEGADO_CANONICO_DIVERGENTE"],1)
        self.assertEqual(report["situacao"],"DIVERGENCIAS_A_RECONCILIAR")
        self.assertFalse(report["promocao_automatica"])

    def test_legado_sem_optin_ou_reserva_e_diagnosticado(self):
        preparar_briefing(self.con,destino="b"*64)
        self.con.execute("""UPDATE briefing_outbox SET status='DELIVERED',
            provider_message_id='wamid.fake' WHERE destinatario_hmac=?""",("b"*64,))
        self.con.commit()
        report=auditar_integridade_envios(self.con)
        self.assertGreaterEqual(report["anomalias"]["LEGADO_SEM_RESERVA_CORRESPONDENTE"],1)
        self.assertGreaterEqual(report["anomalias"]["ACK_SEM_RECIBO_CANONICO"],1)
        self.assertGreaterEqual(report["anomalias"]["LEGADO_SEM_CONSENTIMENTO"],1)
        self.assertGreater(report["total_anomalias"],0)

    def test_reserva_consentimento_revogado_sem_bloqueio_detectado(self):
        self.entregue()
        self.con.execute("UPDATE nivon_consentimentos SET estado='REVOGADO'")
        self.con.commit()
        report=auditar_integridade_envios(self.con)
        self.assertEqual(report["anomalias"]["RESERVA_ATIVA_COM_OPTOUT"],1)
        self.assertEqual(report["anomalias"]["LEGADO_ATIVO_COM_OPTOUT"],1)

    def test_snapshot_esperado_bloqueia_mutacao_durante_backup(self):
        preparar_briefing(self.con,destino="b"*64)
        snapshot=hash_snapshot_legado(self.con)
        outro=abrir_outbox(self.path)
        try:
            outro.execute("""UPDATE briefing_outbox SET status='BLOCKED'
                WHERE destinatario_hmac=?""",("b"*64,))
            outro.commit()
        finally:
            outro.close()
        with self.assertRaisesRegex(ErroControleEnvio,"alteradas desde o backup"):
            registrar_quarentena(
                self.con,registrado_em=AGORA,autorizar_staging=True,
                snapshot_legado_esperado=snapshot,
            )
        self.assertIsNone(self.con.execute(
            "SELECT name FROM sqlite_master WHERE name='nivon_quarentena_legado'"
        ).fetchone())

    def test_backup_logical_detecta_schema_drift_sem_mudar_dados(self):
        # DDL de tabela vazia e trigger adicional devem mudar assinatura,
        # mesmo quando nenhuma linha foi adicionada ou alterada.
        antes=estado_logico(self.con)
        self.con.execute("CREATE TABLE nivon_tabela_vazia_R11 (flag INTEGER)")
        self.con.commit()
        depois=estado_logico(self.con)
        self.assertNotEqual(antes["esquema_sha256"],depois["esquema_sha256"])
        self.assertNotEqual(antes["conteudo_sha256"],depois["conteudo_sha256"])
        self.assertEqual(antes["total_linhas"],depois["total_linhas"])
        self.con.execute("""CREATE TRIGGER nivon_trigger_r11
            AFTER INSERT ON nivon_tabela_vazia_R11
            BEGIN SELECT 1; END""")
        self.con.commit()
        terceira=estado_logico(self.con)
        self.assertNotEqual(depois["esquema_sha256"],terceira["esquema_sha256"])
        self.assertEqual(depois["total_linhas"],terceira["total_linhas"])

    def test_outro_processo_executa_lote_local_sem_reenviar(self):
        self.entregue()
        root=Path(self.tmp.name)/"backup-privado-sintetico"
        root.mkdir()
        env=os.environ.copy()
        env["PYTHONPATH"]=str(Path(__file__).resolve().parents[1]/"src")
        root_repo=Path(__file__).resolve().parents[1]
        base=[sys.executable,"-m","nivon.lote_recuperacao_outbox",
              "--banco",str(self.path)]
        pre=subprocess.run(base,cwd=root_repo,env=env,
                           capture_output=True,text=True,timeout=20,check=True)
        self.assertEqual(json.loads(pre.stdout)["modo"],"SOMENTE_LEITURA")
        self.assertFalse((root/"nivon-antes-migracao.sqlite").exists())
        done=subprocess.run(base+["--diretorio-backup",str(root),
             "--executar-lote-local"],cwd=root_repo,env=env,
             capture_output=True,text=True,timeout=20,check=True)
        result=json.loads(done.stdout)
        self.assertTrue(result["restauracao_validada"])
        self.assertEqual(result["quarentena"]["registrados"],1)
        expected=result["backup_pos_sha256"]
        bkp=verificar_backup(root/"nivon-depois-migracao.sqlite",
                            sha256_esperado=expected)
        self.assertEqual(bkp["conteudo_sha256"],result["conteudo_sha256"])
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM nivon_recibos_canonicos").fetchone()[0],1)
        self.assertNotIn(HASH,done.stdout)
        self.assertNotIn("wamid.r11.synthetic",done.stdout)
        repeat=subprocess.run(base+["--diretorio-backup",str(root),
             "--executar-lote-local"],cwd=root_repo,env=env,
             capture_output=True,text=True,timeout=20)
        self.assertNotEqual(repeat.returncode,0)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM nivon_quarentena_legado").fetchone()[0],1)


if __name__ == "__main__":
    unittest.main()
