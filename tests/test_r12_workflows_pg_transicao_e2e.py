"""R12: integra fixtures REAIS da main, contrato PG e CLI read-only em subprocesso."""
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

from nivon.auditoria_workflows_operacionais import (
    analisar_diretorio, analisar_workflow, ErroAuditoriaWorkflow,
)
from nivon.plano_transicao_outbox_postgres import (
    auditar_arquivo_sqlite, planejar_transicao, validar_contrato_postgres,
    ErroTransicao,
)
from nivon.outbox_briefing import (
    abrir_outbox, agendar_briefing, reservar_para_entrega, registrar_aceite,
    confirmar_entrega,
)
from nivon.outbox_whatsapp import _esquema as whatsapp_esquema
from nivon.outbox_unificada import (
    mensagem_de_prova, registrar_decisao_consentimento,
)

ROOT=Path(__file__).resolve().parents[1]
WORKFLOWS=ROOT/"tests"/"fixtures"/"r12_workflows_main"
SQL_FILE=ROOT/"sql"/"postgres"/"020_outbox_canonica.sql"
SIGNING=b"R12-CHAVE-CONSENTIMENTO-EXCLUSIVA-DO-TESTE-000000000000"
RECIPIENT="c"*64
DAY="2026-10-23"
TS="2026-10-23T12:00:00+00:00"


class TestGovernancaR12(unittest.TestCase):
    def test_oito_workflows_reais_arquivados_fora_do_path_executavel(self):
        self.assertFalse(str(WORKFLOWS).startswith(str(ROOT/".github"/"workflows")))
        report=analisar_diretorio(WORKFLOWS)
        self.assertEqual(report["total"],8)
        self.assertEqual(report["disparos_executados"],0)
        self.assertFalse(report["ativacao_autorizada"])
        items={x["arquivo"]:x for x in report["arquivos"]}
        self.assertEqual(len(items),8)
        self.assertTrue(items["cepea-neon-ingest.yml"]["gatilhos"]["schedule"])
        self.assertTrue(items["conab-neon-ingest.yml"]["oidc_write_declarado"])
        self.assertTrue(items["imea-neon-stage.yml"]["operacao_externa_possivel"])
        self.assertIn("AGENDA_PERIODICA_PRESENTE",
                      items["antt-mdfe-catalogo.yml"]["sinais"])
        self.assertTrue(items["coleta-recorrente-fontes.yml"]["gate_custo_detectado_textualmente"])
        self.assertTrue(items["monitor-p0-operacao.yml"]["gatilhos"]["schedule"])
        self.assertFalse(items["antt-anuario-rgi.yml"]["gatilhos"]["schedule"])
        self.assertTrue(items["ibge-wdi-e2e.yml"]["gatilhos"]["workflow_dispatch"])
        self.assertTrue(all(not x["persistencia_confirmada"] for x in items.values()))
        self.assertTrue(all(not x["licenca_verificada"] for x in items.values()))

    def test_inventario_veta_workflow_inseguro_e_symlink(self):
        with self.assertRaises(ErroAuditoriaWorkflow):
            analisar_workflow("on:\n",nome="ataque.exe")
        with TemporaryDirectory() as t:
            folder=Path(t)
            (folder/"ok.yml").write_text("on:\n  workflow_dispatch:\nname: teste\n")
            (folder/"link.yml").symlink_to(folder/"ok.yml")
            with self.assertRaises(ErroAuditoriaWorkflow):
                analisar_diretorio(folder)

    def test_contrato_postgres_completo_sem_execucao(self):
        result=validar_contrato_postgres(SQL_FILE.read_text())
        self.assertEqual(result["status"],"DDL_ESTATICAMENTE_COMPLETO_NAO_EXECUTADO")
        self.assertEqual(len(result["tabelas"]),5)
        self.assertEqual(len(result["triggers"]),5)
        self.assertFalse(result["teste_em_postgres_real"])
        self.assertFalse(result["implantacao_autorizada"])
        with self.assertRaises(ErroTransicao):
            validar_contrato_postgres(
                SQL_FILE.read_text().replace("CREATE TRIGGER trg_post_guard",
                                             "CREATE TRIGGER trg_post_ausente"))
        with self.assertRaises(ErroTransicao):
            validar_contrato_postgres(
                SQL_FILE.read_text().replace("FOR UPDATE OF c,r",
                                             "FOR UPDATE"))

    def test_cinco_controles_concorrencia_revogacao_do_ddl(self):
        sql=SQL_FILE.read_text()
        self.assertIn("FOR UPDATE",sql)
        self.assertIn("PRIMARY KEY(dia_local,destinatario_hmac)",sql)
        self.assertIn("UNIQUE(canal,intencao_id)",sql)
        self.assertIn("UNIQUE(intencao_id)",sql)
        self.assertIn("revogação terminal",sql)
        self.assertIn("estado='BLOQUEADA_REVOGACAO'",sql)
        self.assertIn("NEW.estado<>'REVOGADO'",sql)
        self.assertNotIn("CREATE EXTENSION",sql)

    def _base(self,path):
        con=abrir_outbox(path)
        whatsapp_esquema(con)
        evidence="CONSENT_R12_TESTE_SINTETICO"
        proof=mensagem_de_prova(
            acao="CONCEDER",destinatario_hmac=RECIPIENT,
            evidencia_id=evidence,em=TS)
        registrar_decisao_consentimento(
            con,acao="CONCEDER",destinatario_hmac=RECIPIENT,
            evidencia_id=evidence,em=TS,
            assinatura=hmac.new(SIGNING,proof,hashlib.sha256).hexdigest(),
            chave_verificacao=SIGNING,
        )
        text="Notícia agrícola sintética - R12, sem mensagem externa"
        item=agendar_briefing(
            con,dia_local=DAY,destinatario_hmac=RECIPIENT,
            briefing={"texto":text,
                      "sha256":hashlib.sha256(text.encode()).hexdigest(),
                      "status":"PREPARADO_SEM_ENVIO"},
            agora=TS,auditoria_aprovada=True,
        )
        reserved=reservar_para_entrega(con,id=item["id"])
        registrar_aceite(
            con,id=item["id"],token=reserved["token"],
            provider_message_id="wamid.R12.SIMULACAO",
        )
        confirmar_entrega(
            con,provider_message_id="wamid.R12.SIMULACAO",
            autenticado=True,quando=TS,
        )
        return con

    def test_transicao_de_clone_consistente_permanece_pendente(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"clone.sqlite"
            db=self._base(path)
            try:
                plan=planejar_transicao(db,sql_postgres=SQL_FILE.read_text())
                self.assertEqual(plan["estado"],"PENDENTE_DE_HOMOLOGACAO_EXTERNA")
                self.assertEqual(plan["reconciliacao"]["total"],0)
                self.assertEqual(plan["reconciliacao"]["legado_total"],1)
                self.assertFalse(plan["banco_postgres_acessado"])
                self.assertFalse(plan["implantacao_autorizada"])
                self.assertFalse(plan["envio_autorizado"])
                self.assertEqual(plan["copias_de_registros_geradas"],0)
                self.assertNotIn(RECIPIENT,json.dumps(plan))
                self.assertNotIn("wamid.R12.SIMULACAO",json.dumps(plan))
            finally:
                db.close()

    def test_drift_recibo_legado_impede_plano_e_preserva_db(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"clone.sqlite"
            db=self._base(path)
            try:
                plan1=planejar_transicao(db,sql_postgres=SQL_FILE.read_text())
                db.execute("UPDATE briefing_outbox SET status='ACCEPTED'")
                db.commit()
                plan2=planejar_transicao(db,sql_postgres=SQL_FILE.read_text())
                self.assertNotEqual(plan1["origen_sqlite"]["digest_logico"],
                                    plan2["origen_sqlite"]["digest_logico"])
                self.assertEqual(plan2["estado"],"BLOQUEADA_POR_DIVERGENCIAS")
                self.assertGreater(plan2["reconciliacao"]["total"],0)
                self.assertEqual(db.execute(
                    "SELECT status FROM briefing_outbox").fetchone()[0],"ACCEPTED")
            finally:
                db.close()

    def test_cli_uma_vez_analisa_workflows_e_clone_sem_rede(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"clone.sqlite"
            db=self._base(path)
            db.close()
            env=os.environ.copy()
            env["PYTHONPATH"]=str(ROOT/"src")
            proc=subprocess.run(
                [sys.executable,"scripts/auditar_workflows_outbox_r12.py",
                 "--workflows-dir",str(WORKFLOWS),
                 "--banco",str(path),"--ddl-postgres",str(SQL_FILE)],
                env=env,cwd=ROOT,capture_output=True,text=True,
                timeout=25,check=True)
            report=json.loads(proc.stdout)
            self.assertEqual(report["modo"],"AUDITORIA_SEM_REDE")
            self.assertEqual(report["workflows"]["total"],8)
            self.assertEqual(report["transicao"]["reconciliacao"]["total"],0)
            self.assertFalse(report["operacao_autorizada"])
            self.assertNotIn(RECIPIENT,proc.stdout)
            self.assertNotIn("wamid.R12.SIMULACAO",proc.stdout)


if __name__=="__main__":
    unittest.main()
