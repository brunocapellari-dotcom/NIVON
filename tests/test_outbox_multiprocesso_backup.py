"""Concorrência SQLite multiprocesso e backup/restore da outbox, sem HTTP."""
import hashlib
import hmac
import json
import multiprocessing
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.autorizacao_envio import conteudo_canonico
from suporte_provas_outbox import provas_sinteticas, provisionar_teste
from nivon.entrega_whatsapp import preparar_template
from nivon.outbox_whatsapp import (
    registrar_edicao, registrar_autorizacao, consultar_envio,
    despachar_registrado, ErroOutbox,
)

SEGREDO=b"segredo_destino_exclusivamente_sintetico_para_testes_2026"
AUDITOR=b"segredo_auditor_exclusivamente_sintetico_para_testes_2026"


def preparar(con):
    modelo = preparar_template(
        destino="5566999999999", template="nivon_briefing_diario",
        resumo="Edição NIVON offline, somente dados sintéticos para teste.",
        link="https://nivon.example/briefings/2026-10-20",
        gerado_em="2026-10-20T07:00:00-03:00",
        opt_in_registrado=True, template_aprovado=True,
    )
    registrar_edicao(con, modelo, edicao="2026-10-20", chave_destinatario=SEGREDO)
    texto="Boletim sintético auditado do NIVON para teste de transação."
    sha=hashlib.sha256(texto.encode()).hexdigest()
    now=datetime.now(timezone.utc)
    raw=json.dumps(modelo["payload"],sort_keys=True,
                   separators=(",",":"),ensure_ascii=False).encode("utf-8")
    doc={
        "idempotency_key":modelo["idempotency_key"],
        "edicao":"2026-10-20",
        "payload_sha256":hashlib.sha256(raw).hexdigest(),
        "sha256_editorial":sha,
        "destinatario_hmac":hmac.new(SEGREDO,modelo["payload"]["to"].encode(),
                                   hashlib.sha256).hexdigest(),
        "revisao_editorial_id":"REVISAO_SINTETICA_20261020",
        "direitos_publicacao_id":"DIREITOS_SINTETICOS_20261020",
        "consentimento_id":"CONSENTIMENTO_SINTETICO_20261020",
        "template_aprovado_id":"TEMPLATE_SINTETICO_20261020",
        "orcamento_id":"ORCAMENTO_SINTETICO_20261020",
        "aprovador_id":"AUDITOR_SINTETICO_INDEPENDENTE",
        "emitido_em":(now-timedelta(minutes=1)).isoformat(),
        "valido_ate":(now+timedelta(hours=1)).isoformat(),
        "revisao_independente":True,
        "direitos_publicacao":True,
        "consentimento_ativo":True,
        "template_aprovado":True,
        "orcamento_aprovado":True,
        "revogado":False,
    }
    sig="sha256="+hmac.new(AUDITOR,conteudo_canonico(doc),hashlib.sha256).hexdigest()
    editorial={
        "estado":"EDICAO_OFFLINE_PREPARADA_SEM_ENVIO",
        "enviado":False, "texto":texto, "sha256":sha,
        "preflight_editorial":{"apto_revisao":True, "bloqueios":[],
                               "modo":"OFFLINE_SEM_ENVIO","sha256_texto":sha}
    }
    comprovantes, emissores = provas_sinteticas(doc)
    provisionar_teste(con, emissores)
    registrar_autorizacao(con,modelo,edicao_editorial=editorial,
                          documento=doc,assinatura=sig,chave_auditoria=AUDITOR,
                          comprovantes=comprovantes, emissores=emissores)
    return modelo,doc,sig,comprovantes,emissores


def tentar_processo(path, modelo, documento, assinatura, comprovantes, emissores, sinal, fila):
    """Executado pelo processo filho: só simula callback, nenhuma rede."""
    con=None
    chamadas=[]
    try:
        con=sqlite3.connect(path,timeout=5)
        if not sinal.wait(6):
            raise RuntimeError("barreira concorrente expirou")
        def callback(p):
            chamadas.append(p["idempotency_key"])
            return {"provider_message_id":"wamid.SIMULADO_20261020"}
        result=despachar_registrado(
            con,modelo,autorizar_envio=True,custos_aprovados=True,
            remetente=callback,documento=documento,
            assinatura=assinatura,chave_auditoria=AUDITOR,
            comprovantes=comprovantes, emissores=emissores)
        fila.put(("ok",result["estado"],len(chamadas)))
    except (ErroOutbox,PermissionError) as exc:
        fila.put(("bloqueado",type(exc).__name__,len(chamadas)))
    except Exception as exc:
        fila.put(("erro",repr(exc),len(chamadas)))
    finally:
        if con is not None:
            con.close()


@unittest.skipUnless(os.name=="posix", "multiprocessos POSIX no CI Ubuntu")
class TestOutboxIntegracaoProcessos(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"envios.sqlite"
        self.con=sqlite3.connect(self.path,timeout=5)
        self.modelo,self.doc,self.sig,self.comprovantes,self.emissores=preparar(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_duas_reservas_simultaneas_so_um_callback(self):
        self.con.close()
        ctx=multiprocessing.get_context("fork")
        barrier=ctx.Event()
        fila=ctx.Queue()
        jobs=[ctx.Process(target=tentar_processo,args=(
            str(self.path),self.modelo,self.doc,self.sig,
            self.comprovantes,self.emissores,barrier,fila))
              for _ in range(2)]
        try:
            for p in jobs:p.start()
            barrier.set()
            for p in jobs:p.join(8)
            for p in jobs:
                if p.is_alive():
                    p.terminate()
                    p.join(2)
                self.assertEqual(p.exitcode,0)
            respostas=[fila.get(timeout=2) for _ in jobs]
            self.assertEqual(sorted(x[0] for x in respostas),["bloqueado","ok"])
            self.assertEqual(sum(x[2] for x in respostas),1)
            self.con=sqlite3.connect(self.path)
            reg=consultar_envio(self.con,self.modelo["idempotency_key"])
            self.assertEqual(reg["tentativas"],1)
            self.assertEqual(reg["estado"],"ACEITO_PROVEDOR")
        finally:
            for p in jobs:
                if p.is_alive():
                    p.terminate()
                    p.join(2)
            fila.close()

    def test_backup_sqlite_apos_timeout_preserva_bloqueio_replay(self):
        chamados=[]
        def timeout(_):
            chamados.append(True)
            raise TimeoutError("falha sintética após reservar")
        r=despachar_registrado(
            self.con,self.modelo,autorizar_envio=True,custos_aprovados=True,
            remetente=timeout,documento=self.doc,assinatura=self.sig,
            chave_auditoria=AUDITOR,
            comprovantes=self.comprovantes, emissores=self.emissores)
        self.assertEqual(r["estado"],"ENVIO_INDETERMINADO")
        self.assertEqual(chamados,[True])
        backup=Path(self.tmp.name)/"copia.sqlite"
        destino=sqlite3.connect(backup)
        try:
            self.con.backup(destino)
        finally:
            destino.close()
        self.con.close()
        self.con=sqlite3.connect(backup)
        with self.assertRaises(ErroOutbox):
            despachar_registrado(
                self.con,self.modelo,autorizar_envio=True,custos_aprovados=True,
                remetente=lambda *_: self.fail("duplicação após restaurar banco"),
                documento=self.doc,assinatura=self.sig,
                chave_auditoria=AUDITOR,
                comprovantes=self.comprovantes, emissores=self.emissores)
        registro=consultar_envio(self.con,self.modelo["idempotency_key"])
        self.assertEqual(registro["tentativas"],1)
        self.assertEqual(registro["estado"],"ENVIO_INDETERMINADO")


if __name__=="__main__":
    unittest.main()
