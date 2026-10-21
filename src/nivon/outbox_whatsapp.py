"""Outbox SQLite transacional para entrega do briefing NIVON via WhatsApp.

Apenas orquestra. NÃO chama rede, NÃO envia automaticamente e NÃO armazena o
telefone, token, payload ou corpo da mensagem em texto claro. A chave do hash de
destinatário é injetada pelo operador (preferencialmente secret manager).
A Cloud API NÃO oferece garantia de idempotência por chave arbitrária:
a intenção é registrada ANTES do POST; timeout -> INDETERMINADO e SEM retry automático.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Callable

from .lineup_nacional import instante
from .autorizacao_envio import verificar_autorizacao


class ErroOutbox(ValueError):
    pass


ESTADOS = frozenset({"PREPARADO", "ENVIO_INDETERMINADO", "ACEITO_PROVEDOR",
                     "ENVIADO", "ENTREGUE", "LIDO", "FALHOU"})
WEBHOOK_ESTADOS = {"sent": "ENVIADO", "delivered": "ENTREGUE",
                   "read": "LIDO", "failed": "FALHOU"}
ORDEM = {"ENVIO_INDETERMINADO": 0, "ACEITO_PROVEDOR": 1,
         "ENVIADO": 2, "ENTREGUE": 3, "LIDO": 4}


def _hora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _secret(secret: bytes) -> bytes:
    if not isinstance(secret, bytes) or len(secret) < 24:
        raise ErroOutbox("chave HMAC do operador ausente ou curta")
    return secret


def _revisar_preparado(preparado: dict) -> tuple[str,str,str]:
    if not isinstance(preparado, dict) or preparado.get("estado") != "PREPARADO_NAO_ENVIADO":
        raise ErroOutbox("modelo WhatsApp não preparado")
    payload = preparado.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "template":
        raise ErroOutbox("somente template preparado e aprovado pelo canal")
    destino=payload.get("to")
    template=payload.get("template", {}).get("name")
    chave=preparado.get("idempotency_key")
    if not isinstance(destino,str) or not re.fullmatch(r"[0-9]{10,15}",destino):
        raise ErroOutbox("destinatário internacional inválido")
    if not isinstance(template,str) or not re.fullmatch(r"[a-z][a-z0-9_]{2,100}",template):
        raise ErroOutbox("template inválido")
    if not isinstance(chave,str) or not re.fullmatch(r"[0-9a-f]{64}",chave):
        raise ErroOutbox("idempotência do preparado inválida")
    return destino,template,chave


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def _esquema(con: sqlite3.Connection) -> None:
    if con.in_transaction:
        raise ErroOutbox("conexão deve estar sem transação antes de iniciar a outbox")
    con.execute("""CREATE TABLE IF NOT EXISTS nivon_envios (
        idempotency_key TEXT PRIMARY KEY,
        edicao TEXT NOT NULL,
        destinatario_hmac TEXT NOT NULL,
        template TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        estado TEXT NOT NULL,
        preparado_em TEXT NOT NULL,
        atualizado_em TEXT NOT NULL,
        provider_message_id TEXT UNIQUE,
        tentativas INTEGER NOT NULL DEFAULT 0,
        UNIQUE(edicao,destinatario_hmac,template))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_nivon_envios_provider ON nivon_envios(provider_message_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_nivon_envios_estado ON nivon_envios(estado)")
    con.execute("""CREATE TABLE IF NOT EXISTS nivon_autorizacoes (
        idempotency_key TEXT PRIMARY KEY REFERENCES nivon_envios(idempotency_key),
        documento_sha256 TEXT NOT NULL,
        sha256_editorial TEXT NOT NULL,
        valido_ate TEXT NOT NULL,
        revogado_em TEXT,
        criado_em TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS nivon_revogacoes (
        idempotency_key TEXT PRIMARY KEY REFERENCES nivon_envios(idempotency_key),
        evidencia_sha256 TEXT NOT NULL,
        revogado_em TEXT NOT NULL)""")


def registrar_edicao(con: sqlite3.Connection, preparado: dict, *,
                    edicao: str, chave_destinatario: bytes) -> dict:
    """Um briefing/destinatário/template por edição; sem armazenar PII reversível."""
    _secret(chave_destinatario)
    instante(preparado.get("gerado_em"))
    if not isinstance(edicao,str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}",edicao):
        raise ErroOutbox("edição exige YYYY-MM-DD")
    try:
        datetime.strptime(edicao,"%Y-%m-%d")
    except ValueError as exc:
        raise ErroOutbox("data da edição inválida") from exc
    destino,template,chave=_revisar_preparado(preparado)
    digest=hmac.new(chave_destinatario,destino.encode(),hashlib.sha256).hexdigest()
    fp=_fingerprint(preparado["payload"])
    _esquema(con)
    con.execute("BEGIN IMMEDIATE")
    try:
        existe=con.execute("""SELECT idempotency_key, payload_sha256, estado
            FROM nivon_envios WHERE edicao=? AND destinatario_hmac=? AND template=?""",
            (edicao,digest,template)).fetchone()
        if existe:
            if existe[0]!=chave or existe[1]!=fp:
                raise ErroOutbox("segunda versão da mesma edição: revisão manual antes de reenviar")
            estado=existe[2]
        else:
            agora=_hora()
            con.execute("""INSERT INTO nivon_envios
                (idempotency_key,edicao,destinatario_hmac,template,payload_sha256,
                 estado,preparado_em,atualizado_em,tentativas)
                VALUES (?,?,?,?,?,?,?,?,0)""",
                (chave,edicao,digest,template,fp,"PREPARADO",agora,agora))
            estado="PREPARADO"
        con.commit()
        return {"chave":chave,"edicao":edicao,"estado":estado,"ja_existia":bool(existe)}
    except Exception:
        con.rollback()
        raise


def consultar_envio(con: sqlite3.Connection, chave: str) -> dict:
    _esquema(con)
    result=con.execute("""SELECT idempotency_key, edicao, estado,
                 provider_message_id, tentativas, atualizado_em
                 FROM nivon_envios WHERE idempotency_key=?""",(chave,)).fetchone()
    if not result:
        raise ErroOutbox("edição não registrada")
    return dict(zip(("chave","edicao","estado","provider_message_id","tentativas",
                     "atualizado_em"),result))


def registrar_autorizacao(con: sqlite3.Connection, preparado: dict, *, 
                           edicao_editorial: dict, documento: dict,
                           assinatura: str, chave_auditoria: bytes) -> dict:
    """Persiste apenas o SHA do documento assinado, nunca o texto/telefone.

    O documento e a edição são insumos de governança EXTERNOS: a verificação
    criptográfica não demonstra que o aprovador de fato tinha autoridade.
    """
    if not isinstance(edicao_editorial, dict) or (
            edicao_editorial.get("estado") != "EDICAO_OFFLINE_PREPARADA_SEM_ENVIO"
            or edicao_editorial.get("enviado") is not False):
        raise ErroOutbox("edição editorial ainda não preparada para revisão")
    texto = edicao_editorial.get("texto")
    if not isinstance(texto, str):
        raise ErroOutbox("texto editorial ausente")
    sha = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    if (edicao_editorial.get("sha256") != sha
            or documento.get("sha256_editorial") != sha):
        raise ErroOutbox("edição editorial diverge do hash da aprovação")
    relatorio = edicao_editorial.get("preflight_editorial")
    if (not isinstance(relatorio, dict)
            or relatorio.get("apto_revisao") is not True
            or relatorio.get("sha256_texto") != sha
            or relatorio.get("bloqueios") != []
            or relatorio.get("modo") != "OFFLINE_SEM_ENVIO"):
        raise ErroOutbox("revisão editorial independente não comprovada no pacote")
    digest_doc = verificar_autorizacao(documento, assinatura, chave_auditoria=chave_auditoria)
    destino, template, chave = _revisar_preparado(preparado)
    del destino, template  # não salvar telefone nem template nesta tabela
    _esquema(con)
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute("""SELECT edicao,destinatario_hmac,payload_sha256,estado
                            FROM nivon_envios WHERE idempotency_key=?""", (chave,)).fetchone()
        if row is None or row[3] != "PREPARADO":
            raise ErroOutbox("reserva editorial requer registro PREPARADO sem tentativas")
        if (documento["idempotency_key"] != chave
                or documento["edicao"] != row[0]
                or documento["destinatario_hmac"] != row[1]
                or documento["payload_sha256"] != row[2]
                or _fingerprint(preparado["payload"]) != row[2]):
            raise ErroOutbox("autorização não corresponde a edição, destino ou payload")
        existente = con.execute("""SELECT documento_sha256,revogado_em
                                   FROM nivon_autorizacoes WHERE idempotency_key=?""",
                                (chave,)).fetchone()
        if existente and (existente[0] != digest_doc or existente[1] is not None):
            raise ErroOutbox("aprovação anterior divergente/revogada; nova revisão obrigatória")
        if not existente:
            con.execute("""INSERT INTO nivon_autorizacoes
                           (idempotency_key,documento_sha256,sha256_editorial,
                            valido_ate,revogado_em,criado_em)
                           VALUES (?,?,?,?,NULL,?)""",
                        (chave, digest_doc, sha, documento["valido_ate"], _hora()))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return {"chave": chave, "estado": "AUTORIZACAO_REGISTRADA_SEM_ENVIO",
            "documento_sha256": digest_doc}


def revogar_autorizacao(con: sqlite3.Connection, *, chave: str,
                       evidencia_revogacao: str) -> dict:
    """Bloqueia novas reservas; não desfaz POST eventualmente já efetuado."""
    if (not isinstance(evidencia_revogacao, str)
            or not re.fullmatch(r"[A-Za-z0-9._:-]{12,128}", evidencia_revogacao)):
        raise ErroOutbox("revogação exige registro identificável")
    _esquema(con)
    con.execute("BEGIN IMMEDIATE")
    try:
        r = con.execute("""SELECT e.estado,a.revogado_em
                           FROM nivon_envios e JOIN nivon_autorizacoes a
                           ON e.idempotency_key=a.idempotency_key
                           WHERE e.idempotency_key=?""", (chave,)).fetchone()
        if not r:
            raise ErroOutbox("aprovação a revogar não encontrada")
        if r[1] is None:
            instante = _hora()
            con.execute("UPDATE nivon_autorizacoes SET revogado_em=? WHERE idempotency_key=?",
                        (instante, chave))
            # Manter prova pseudonimizada e imutável de opt-out em transação
            # conjunta à revogação; não persistir documentos pessoais brutos.
            con.execute("""INSERT INTO nivon_revogacoes
                           (idempotency_key,evidencia_sha256,revogado_em)
                           VALUES (?,?,?)""",
                        (chave, hashlib.sha256(evidencia_revogacao.encode("utf-8")).hexdigest(),
                         instante))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return {"chave": chave, "estado": "AUTORIZACAO_REVOGADA",
            "envio_em_andamento_ou_anterior": r[0] != "PREPARADO"}


def despachar_registrado(con: sqlite3.Connection, preparado: dict, *,
                        autorizar_envio: bool = False, custos_aprovados: bool = False,
                        remetente: Callable[[dict],dict] | None = None,
                        documento: dict | None = None, assinatura: str | None = None,
                        chave_auditoria: bytes | None = None) -> dict:
    """Reserva atomicamente a primeira e ÚNICA tentativa. Nada é repetido.

    A conexão deve apontar para disco durável com backup; teste não é prova de
    durabilidade em nuvem. Um crash após reserva exige reconciliação humana.
    """
    if not autorizar_envio or not custos_aprovados:
        raise PermissionError("envio e orçamento não autorizados")
    if remetente is None:
        raise ErroOutbox("provedor WhatsApp não conectado")
    # Assinatura e documento são condição necessária, não autorização isolada.
    # Mesmo um callback injetado só é chamado após prova persistida na outbox.
    if documento is None or assinatura is None or chave_auditoria is None:
        raise PermissionError("autorização editorial registrada e assinada obrigatória")
    digest_doc = verificar_autorizacao(documento, assinatura,
                                     chave_auditoria=chave_auditoria)
    _,_,chave=_revisar_preparado(preparado)
    _esquema(con)
    con.execute("BEGIN IMMEDIATE")
    try:
        d=con.execute("""SELECT e.estado,e.payload_sha256,e.edicao,e.destinatario_hmac,
                           a.documento_sha256,a.sha256_editorial,a.revogado_em
                           FROM nivon_envios e LEFT JOIN nivon_autorizacoes a
                           ON e.idempotency_key=a.idempotency_key
                           WHERE e.idempotency_key=?""", (chave,)).fetchone()
        if not d:
            raise ErroOutbox("envio não registrado antes do POST")
        if d[0]!="PREPARADO":
            raise ErroOutbox("envio já reservado/realizado: sem retry automático")
        if d[1]!=_fingerprint(preparado["payload"]):
            raise ErroOutbox("conteúdo divergente do registrado")
        if (d[4] != digest_doc or d[5] != documento.get("sha256_editorial")
                or d[6] is not None or d[2] != documento.get("edicao")
                or d[3] != documento.get("destinatario_hmac")
                or chave != documento.get("idempotency_key")
                or d[1] != documento.get("payload_sha256")):
            raise PermissionError("outbox sem aprovação válida, vinculada ou não revogada")
        con.execute("""UPDATE nivon_envios
                       SET estado='ENVIO_INDETERMINADO',tentativas=1,atualizado_em=?
                       WHERE idempotency_key=?""",(_hora(),chave))
        con.commit()
    except Exception:
        con.rollback()
        raise
    # Não há exceção que autorize repetir o POST com a mesma edição.
    try:
        resposta=remetente(preparado)
        provider_id=resposta.get("provider_message_id") if isinstance(resposta,dict) else None
        if not isinstance(provider_id,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{4,220}",provider_id):
            raise ErroOutbox("ACK sem provider_message_id")
    except Exception:
        return {"chave":chave,"estado":"ENVIO_INDETERMINADO","enviado_confirmado":False,
                "nota":"verificar no provedor antes de nova tentativa; nunca reenviar automaticamente"}
    con.execute("BEGIN IMMEDIATE")
    try:
        estado=con.execute("SELECT estado FROM nivon_envios WHERE idempotency_key=?",
                           (chave,)).fetchone()[0]
        # Webhook pode chegar antes do ACK; não rebaixar status.
        novo="ACEITO_PROVEDOR" if estado=="ENVIO_INDETERMINADO" else estado
        con.execute("""UPDATE nivon_envios SET provider_message_id=?,estado=?,atualizado_em=?
                       WHERE idempotency_key=?""",(provider_id,novo,_hora(),chave))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return {"chave":chave,"estado":novo,"enviado_confirmado":True,
            "nota":"aceito pelo provedor não garante entrega ao destinatário"}


def aplicar_status_assinado(con: sqlite3.Connection, *, corpo: bytes,
                           assinatura: str, app_secret: bytes) -> dict:
    """Verifica X-Hub-Signature-256 e processa ACKs de status da Meta.

    Retorna contadores; webhook autenticado de outro telefone não altera
    registro cujo provider_message_id desconhecemos.
    """
    _secret(app_secret)
    if not isinstance(corpo,bytes) or not 0 < len(corpo)<=180_000:
        raise ErroOutbox("webhook ausente ou excessivo")
    if not isinstance(assinatura,str) or not re.fullmatch(r"sha256=[a-f0-9]{64}",assinatura):
        raise PermissionError("assinatura webhook ausente/inválida")
    esperado="sha256="+hmac.new(app_secret,corpo,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperado,assinatura):
        raise PermissionError("assinatura webhook não corresponde ao app secret")
    try:
        obj=json.loads(corpo)
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ErroOutbox("webhook JSON inválido") from exc
    if not isinstance(obj,dict) or obj.get("object")!="whatsapp_business_account":
        raise ErroOutbox("webhook não pertence ao WhatsApp")
    updates=[]
    for entry in obj.get("entry",[]):
        for change in entry.get("changes",[]):
            if change.get("field")!="messages":
                continue
            for s in change.get("value",{}).get("statuses",[]):
                pid=s.get("id")
                status=WEBHOOK_ESTADOS.get(s.get("status"))
                if status and isinstance(pid,str) and len(pid)<=220:
                    updates.append((pid,status))
    _esquema(con)
    mudancas=0;ignoradas=0
    con.execute("BEGIN IMMEDIATE")
    try:
        for pid,novo in updates:
            row=con.execute("SELECT idempotency_key,estado FROM nivon_envios WHERE provider_message_id=?",
                            (pid,)).fetchone()
            if not row:
                ignoradas+=1
                continue
            chave,atual=row
            if atual=="FALHOU" or (novo=="FALHOU" and atual in {"ENTREGUE","LIDO"}):
                ignoradas+=1
                continue
            if novo!="FALHOU" and ORDEM.get(novo,0)<=ORDEM.get(atual,0):
                ignoradas+=1
                continue
            con.execute("UPDATE nivon_envios SET estado=?, atualizado_em=? WHERE idempotency_key=?",
                        (novo,_hora(),chave))
            mudancas+=1
        con.commit()
    except Exception:
        con.rollback()
        raise
    return {"recebidos":len(updates),"atualizados":mudancas,
            "ignorados_ou_sem_correspondencia":ignoradas,
            "estado":"WEBHOOK_AUTENTICADO_PROCESSADO"}


def vincular_ack_verificado(con: sqlite3.Connection, *, chave: str,
                            provider_message_id: str, evidencia_conciliacao: str) -> dict:
    """Recuperação manual de timeout com prova de mensagem no provedor."""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{4,220}",provider_message_id):
        raise ErroOutbox("message id inválido")
    if not isinstance(evidencia_conciliacao,str) or not re.fullmatch(r"[A-Za-z0-9_:.-]{12,120}",evidencia_conciliacao):
        raise ErroOutbox("identificador de evidência humana obrigatório")
    _esquema(con)
    con.execute("BEGIN IMMEDIATE")
    try:
        r=con.execute("SELECT estado FROM nivon_envios WHERE idempotency_key=?",(chave,)).fetchone()
        if not r or r[0]!="ENVIO_INDETERMINADO":
            raise ErroOutbox("conciliação exige envio anteriormente indeterminado")
        con.execute("""UPDATE nivon_envios SET provider_message_id=?,
                        estado='ACEITO_PROVEDOR', atualizado_em=? WHERE idempotency_key=?""",
                    (provider_message_id,_hora(),chave))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return {"chave":chave,"estado":"ACEITO_PROVEDOR",
            "nota":"vínculo inserido com evidência externa; prova de entrega exige webhook"}
