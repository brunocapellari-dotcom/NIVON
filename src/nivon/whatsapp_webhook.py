"""Webhook WhatsApp Cloud API: assinatura Meta + recibos de entrega na outbox.

Esta função NÃO configura HTTP server, não recebe credenciais via corpo JSON,
não envia mensagens e não loga telefones/conteúdo individual. O gateway deve
passar os bytes originais e o cabeçalho X-Hub-Signature-256 sem modificar.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3

from .outbox_briefing import confirmar_entrega, ErroOutbox


class ErroWebhook(ValueError):
    pass


_ASSINATURA = re.compile(r"sha256=([0-9a-f]{64})\Z")
_MSG_ID = re.compile(r"[A-Za-z0-9_.:@-]{1,256}\Z")


def verificar_assinatura(*, raw_body: bytes, signature: str,
                        app_secret: str) -> None:
    """Exige segredo >=32 bytes; comparação resistente a timing attack."""
    if not isinstance(raw_body, bytes) or not 0 < len(raw_body) <= 256_000:
        raise ErroWebhook("corpo webhook inválido ou excessivo")
    if not isinstance(signature, str):
        raise PermissionError("assinatura webhook ausente")
    match = _ASSINATURA.fullmatch(signature)
    if match is None:
        raise PermissionError("assinatura webhook malformada")
    if not isinstance(app_secret, str) or len(app_secret.encode("utf-8")) < 32:
        raise PermissionError("app secret ausente ou fraco")
    digest = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(match.group(1), digest):
        raise PermissionError("assinatura webhook não confere")


def aplicar_webhook_entregas(db: sqlite3.Connection, *, raw_body: bytes,
                             signature: str, app_secret: str) -> dict:
    """Processa exclusivamente statuses 'delivered' de webhook assinado.

    Não confundir 'sent', 'read' ou status de mensagem recebida com entrega.
    Recibo desconhecido/repetido é informado como pendente de reconciliação,
    sem tocar em outro ID; não eleva estado de mensagem sem registro local.
    """
    verificar_assinatura(raw_body=raw_body, signature=signature,
                        app_secret=app_secret)
    try:
        evento = json.loads(raw_body)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroWebhook("JSON webhook inválido") from exc
    if not isinstance(evento, dict) or evento.get("object") != "whatsapp_business_account":
        raise ErroWebhook("evento webhook não é WhatsApp Cloud API")
    entries=evento.get("entry")
    if not isinstance(entries, list) or len(entries) > 100:
        raise ErroWebhook("entries inválidas")
    # Validar todos os recibos antes de alterar o banco (falha atômica para
    # formatos inválidos, sem executar updates parciais da mesma requisição).
    delivered=[]
    outros=0
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("changes"), list):
            raise ErroWebhook("entry malformada")
        if len(entry["changes"]) > 100:
            raise ErroWebhook("limite de changes")
        for change in entry["changes"]:
            if not isinstance(change, dict) or change.get("field") != "messages":
                raise ErroWebhook("tipo de change não reconhecido")
            value=change.get("value")
            if not isinstance(value, dict):
                raise ErroWebhook("value malformado")
            statuses = value.get("statuses", [])
            if not isinstance(statuses, list) or len(statuses) > 100:
                raise ErroWebhook("statuses precisa ser lista de tamanho limitado")
            for st in statuses:
                if not isinstance(st, dict):
                    raise ErroWebhook("status inválido")
                msgid=st.get("id")
                if not isinstance(msgid, str) or not _MSG_ID.fullmatch(msgid):
                    raise ErroWebhook("ID de mensagem inválido")
                status=st.get("status")
                if status == "delivered":
                    timestamp=st.get("timestamp")
                    if not isinstance(timestamp, str) or not re.fullmatch(r"\d{10,13}", timestamp):
                        raise ErroWebhook("timestamp de entrega inválido")
                    from datetime import datetime, timezone
                    try:
                        instante=datetime.fromtimestamp(int(timestamp),tz=timezone.utc)
                    except (OverflowError,ValueError,OSError) as exc:
                        raise ErroWebhook("timestamp de entrega fora de intervalo") from exc
                    delivered.append((msgid,instante.isoformat()))
                elif status in {"sent","read","failed"}:
                    outros+=1
                else:
                    raise ErroWebhook("status desconhecido")
    confirmadas=0
    nao_correspondentes=0
    # Um webhook assinado não substitui prova de aceite local.
    for msgid,quando in delivered:
        try:
            confirmar_entrega(
                db,provider_message_id=msgid,autenticado=True,quando=quando)
            confirmadas+=1
        except ErroOutbox:
            nao_correspondentes+=1
    return {"status":"WEBHOOK_AUTENTICADO_PROCESSADO",
            "confirmadas":confirmadas,"nao_correspondentes":nao_correspondentes,
            "outros_status_sem_promocao":outros}
