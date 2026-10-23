"""R10: lote E2E da migração e recuperação; NENHUM provedor, rede ou custo."""
import hashlib
import hmac
import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nivon.outbox_briefing import (
    abrir_outbox, agendar_briefing, reservar_para_entrega,
    registrar_aceite, confirmar_entrega,
)
from nivon.outbox_whatsapp import (
    registrar_edicao, despachar_registrado, aplicar_status_assinado,
)
from nivon.entrega_whatsapp import preparar_template
from nivon.outbox_unificada import (
    mensagem_de_prova, registrar_decisao_consentimento, ErroControleEnvio,
)
from nivon.outbox_recibos import consultar_recibo
from nivon.migracao_outbox_legada import planejar_migracao, registrar_quarentena
from nivon.lote_recuperacao_outbox import executar_lote, main as lote_main
from nivon.backup_outbox import (
    criar_backup_validado, restaurar_backup_validado, verificar_backup,
    estado_logico, ErroBackup,
)

SECRET=b"R10-CHAVE-CONSENTIMENTO-SINTETICO-NAO-PRODUCAO-000000"
DEST_SECRET=b"R10-DESTINATARIO-TESTE-NAO-PRODUCAO-COMPARTILHADO-000"
META=b"R10-META-ASSINATURA-SINTETICA-NAO-PRODUCAO-00000"
PHONE="5566999999999"
SHA_WPP=hmac.new(DEST_SECRET,PHONE.encode(),hashlib.sha256).hexdigest()
DAY1="2026-10-20"
DAY2="2026-10-21"
TS="2026-10-20T12:00:00+00:00"


def consentir(db, destinatario, acao="CONCEDER", instante=TS):
    evid="CONSENT-R10-TEST-SINTETICO" if acao=="CONCEDER" else "OPTOUT-R10-TEST-SINTETICO"
    proof=mensagem_de_prova(acao=acao,destinatario_hmac=destinatario,
                           evidencia_id=evid,em=instante)
    sign=hmac.new(SECRET,proof,hashlib.sha256).hexdigest()
    return registrar_decisao_consentimento(
        db,acao=acao,destinatario_hmac=destinatario,
        evidencia_id=evid,em=instante,assinatura=sign,
        chave_verificacao=SECRET,
    )


def criar_briefing(db,destino,dia=DAY1):
    text="Resumo do agronegócio com fontes SINTÉTICAS R10."
    created=agendar_briefing(
        db,dia_local=dia,destinatario_hmac=destino,
        briefing={"status":"PREPARADO_SEM_ENVIO","texto":text,
                  "sha256":hashlib.sha256(text.encode()).hexdigest()},
        agora=TS,auditoria_aprovada=True,
    )
    return created


class TestMigracaoBackupR10(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.path=self.root/"outbox-atual.sqlite"
        self.db=abrir_outbox(self.path)
        self.digest="a"*64
        consentir(self.db,self.digest)
        consentir(self.db,SHA_WPP)
        briefing=criar_briefing(self.db,self.digest)
        slot=reservar_para_entrega(self.db,id=briefing["id"])
        registrar_aceite(self.db,id=briefing["id"],token=slot["token"],
                         provider_message_id="wamid.R10-BRIEFING")
        confirmar_entrega(self.db,provider_message_id="wamid.R10-BRIEFING",
                          autenticado=True,quando=TS)
        self.modelo=preparar_template(
            destino=PHONE,template="nivon_briefing_diario",
            resumo="Resumo sintético sobre o clima, portos e soja do NIVON.",
            link="https://nivon.example/teste-r10",
            gerado_em="2026-10-21T08:00:00-03:00",
            opt_in_registrado=True,template_aprovado=True,
        )
        registrar_edicao(self.db,self.modelo,edicao=DAY2,chave_destinatario=DEST_SECRET)
        despachar_registrado(
            self.db,self.modelo,autorizar_envio=True,custos_aprovados=True,
            remetente=lambda _:{"provider_message_id":"wamid.R10-WHATSAPP"},
        )
        raw=json.dumps({"object":"whatsapp_business_account","entry":[{
            "changes":[{"field":"messages","value":{"statuses":[{
                "id":"wamid.R10-WHATSAPP","status":"delivered",
                "timestamp":"1792502400",
            }]}}]
        }]}).encode()
        sig="sha256="+hmac.new(META,raw,hashlib.sha256).hexdigest()
        aplicar_status_assinado(self.db,corpo=raw,assinatura=sig,app_secret=META)
        self.noopt="b"*64
        self.legacy_id=criar_briefing(self.db,self.noopt)["id"]

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_inventario_sem_promocao_e_com_ausencia_optin(self):
        plano=planejar_migracao(self.db)
        self.assertEqual(plano["total"],3)
        self.assertEqual(plano["grupos"]["CONSENTIMENTO_NAO_COMPROVADO"],1)
        self.assertEqual(plano["envios_novos"],0)
        self.assertFalse(plano["publicacao_autorizada"])
        self.assertTrue(all(not x["promocao_permitida"] for x in plano["registros"]))
        self.assertFalse(self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='nivon_quarentena_legado'"
        ).fetchone())

    def test_stage_idempotente_e_preserva_estados_legados(self):
        with self.assertRaises(PermissionError):
            registrar_quarentena(self.db,registrado_em=TS)
        a=registrar_quarentena(
            self.db,autorizar_staging=True,registrado_em=TS)
        b=registrar_quarentena(
            self.db,autorizar_staging=True,registrado_em=TS)
        self.assertEqual((a["registrados"],a["total"]),(3,3))
        self.assertEqual((b["registrados"],b["ja_existentes"]),(0,3))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_quarentena_legado").fetchone()[0],3)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_recibos_canonicos").fetchone()[0],2)
        self.assertEqual(consultar_recibo(
            self.db,provider_message_id="wamid.R10-WHATSAPP")["estado"],"ENTREGUE")

    def test_alteracao_legacy_pos_quarentena_falha_sem_perda(self):
        registrar_quarentena(self.db,autorizar_staging=True,registrado_em=TS)
        self.db.execute("UPDATE briefing_outbox SET status='BLOCKED' WHERE id=?",
                        (self.legacy_id,))
        self.db.commit()
        with self.assertRaises(ErroControleEnvio):
            registrar_quarentena(self.db,autorizar_staging=True,registrado_em=TS)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_quarentena_legado").fetchone()[0],3)

    def test_reconciliacao_duplicata_outro_canal_so_quarentena(self):
        # Colisão de mesmo dia+destinatário não inventa nova reserva.
        legacy=criar_briefing(self.db,SHA_WPP,dia=DAY2)
        self.assertIsNotNone(legacy["id"])
        plano=planejar_migracao(self.db)
        duplicados=[x for x in plano["registros"]
                    if x["motivo"]=="DUPLICIDADE_DIA_DESTINATARIO"]
        self.assertEqual(len(duplicados),2)
        self.assertEqual(plano["envios_novos"],0)

    def test_backup_restauracao_full_e_checksum_sem_perda(self):
        registrar_quarentena(self.db,autorizar_staging=True,registrado_em=TS)
        backup=self.root/"backup-consistente.sqlite"
        manifest=criar_backup_validado(
            self.db,destino=backup,autorizar_backup=True,
        )
        self.assertEqual(manifest["estado"],"BACKUP_VALIDADO_LOCAL")
        self.assertEqual(manifest["conteudo_sha256"],
                         estado_logico(self.db)["conteudo_sha256"])
        restore=self.root/"restaurado.sqlite"
        res=restaurar_backup_validado(
            backup,destino=restore,
            sha256_esperado=manifest["arquivo_sha256"],
            autorizar_restauracao=True,
        )
        self.assertEqual(res["conteudo_sha256"],manifest["conteudo_sha256"])
        cloned=abrir_outbox(restore)
        try:
            self.assertEqual(estado_logico(cloned),estado_logico(self.db))
            self.assertEqual(consultar_recibo(
                cloned,provider_message_id="wamid.R10-BRIEFING")["estado"],"ENTREGUE")
            self.assertEqual(consultar_recibo(
                cloned,provider_message_id="wamid.R10-WHATSAPP")["estado"],"ENTREGUE")
            self.assertEqual(cloned.execute(
                "SELECT COUNT(*) FROM nivon_quarentena_legado").fetchone()[0],3)
            self.assertEqual(cloned.execute(
                "SELECT estado FROM nivon_consentimentos WHERE destinatario_hmac=?",
                (SHA_WPP,)).fetchone()[0],"CONCEDIDO")
        finally:
            cloned.close()
        with self.assertRaises(FileExistsError):
            restaurar_backup_validado(
                backup,destino=restore,sha256_esperado=manifest["arquivo_sha256"],
                autorizar_restauracao=True,
            )

    def test_backup_malicioso_tamper_nao_restauravel(self):
        backup=self.root/"backup.sqlite"
        m=criar_backup_validado(self.db,destino=backup,autorizar_backup=True)
        adulterado=self.root/"adulterado.sqlite"
        shutil.copy2(backup,adulterado)
        with adulterado.open("ab") as f:
            f.write(b"TAMPER")
        with self.assertRaises(ErroBackup):
            restaurar_backup_validado(
                adulterado,destino=self.root/"restore-denied.sqlite",
                sha256_esperado=m["arquivo_sha256"],
                autorizar_restauracao=True)
        self.assertFalse((self.root/"restore-denied.sqlite").exists())

    def test_pipeline_unico_planeja_sem_criar_tabelas_e_restaura_em_lote(self):
        root=self.root/"recuperacao"
        root.mkdir()
        estado_antes=estado_logico(self.db)
        result=executar_lote(banco=self.path)
        self.assertEqual(result["modo"],"SOMENTE_LEITURA")
        self.assertEqual(result["auditoria"]["total"],3)
        self.assertFalse(result["envio_executado"])
        self.assertEqual(estado_antes,estado_logico(self.db))
        self.assertFalse((root/"nivon-antes-migracao.sqlite").exists())
        with self.assertRaises(PermissionError):
            executar_lote(banco=self.path,aplicar_quarentena=True)
        after=executar_lote(
            banco=self.path,pasta_segura=root,
            aplicar_quarentena=True,agora=TS,
        )
        self.assertEqual(after["modo"],"QUARENTENA_E_BACKUP_LOCAL")
        self.assertTrue(after["restauracao_validada"])
        self.assertEqual(after["quarentena"]["registrados"],3)
        self.assertEqual(len(list(root.glob("*.sqlite"))),3)
        self.assertEqual(after["conteudo_sha256"],estado_logico(self.db)["conteudo_sha256"])
        with self.assertRaises(FileExistsError):
            executar_lote(
                banco=self.path,pasta_segura=root,aplicar_quarentena=True,agora=TS,
            )

    def test_cli_auditoria_somente_leitura_sem_rede(self):
        from unittest.mock import patch
        import io
        stream=io.StringIO()
        with patch("sys.stdout",stream):
            code=lote_main(["--banco",str(self.path)])
        self.assertEqual(code,0)
        obj=json.loads(stream.getvalue())
        self.assertEqual(obj["modo"],"SOMENTE_LEITURA")
        self.assertEqual(obj["auditoria"]["total"],3)
        self.assertFalse(obj["envio_executado"])
        self.assertNotIn(PHONE,stream.getvalue())
        self.assertNotIn(SHA_WPP,stream.getvalue())

    def test_backup_restauracao_tem_flags_e_nao_sobrescreve(self):
        target=self.root/"backup.sqlite"
        with self.assertRaises(PermissionError):
            criar_backup_validado(self.db,destino=target)
        self.assertFalse(target.exists())
        m=criar_backup_validado(self.db,destino=target,autorizar_backup=True)
        self.assertEqual(verificar_backup(
            target,sha256_esperado=m["arquivo_sha256"])["integridade"],"OK")
        with self.assertRaises(FileExistsError):
            criar_backup_validado(self.db,destino=target,autorizar_backup=True)
        with self.assertRaises(PermissionError):
            restaurar_backup_validado(
                target,destino=self.root/"restore.sqlite",
                sha256_esperado=m["arquivo_sha256"])
        self.assertFalse((self.root/"restore.sqlite").exists())


if __name__=="__main__":
    unittest.main()
