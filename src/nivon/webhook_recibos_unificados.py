"""Entrada única de estados Meta: duas outboxes, um commit canônico.

Não executa HTTP, não envia, não registra PII/payload. WSGI deve verificar
seu próprio acesso de rede, tamanho e caminho; assinatura verificada AQUI.
Evento inválido causa rollback de toda a notificação, nunca meia atualização.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone

from .whatsapp_webhook import ErroWebhook, verificar_assinatura
from .outbox_whatsapp import _esquema as _whatsapp_esquema, WEBHOOK_ESTADOS
from .outbox_recibos import preparar_recibos, aplicar_recibo_na_transacao

_PID = re.compile(r"[A-Za-z0-9_.:@-]{1,256}\Z")
_STATES = frozenset(WEBHOOK_ESTADOS)


def _eventos(raw_body: bytes) -> list[tuple[str,str,str]]:
    try:
        obj=json.loads(raw_body)
    except (TypeError,UnicodeError,json.JSONDecodeError) as exc:
        raise ErroWebhook("JSON de status inválido") from exc
    if not isinstance(obj,dict) or obj.get("object")!="whatsapp_business_account":
        raise ErroWebhook("objeto de evento incompatível")
    entries=obj.get("entry")
    if not isinstance(entries,list) or len(entries)>100:
        raise ErroWebhook("lista de eventos inválida")
    eventos=[]
    for entry in entries:
        changes=entry.get("changes") if isinstance(entry,dict) else None
        if not isinstance(changes,list) or len(changes)>100:
            raise ErroWebhook("changes inválido")
        for change in changes:
            if not isinstance(change,dict) or change.get("field")!="messages":
                raise ErroWebhook("change de tipo desconhecido")
            value=change.get("value")
            statuses=value.get("statuses",[]) if isinstance(value,dict) else None
            if not isinstance(statuses,list) or len(statuses)>100:
                raise ErroWebhook("statuses inválidos")
            for item in statuses:
                if not isinstance(item,dict):
                    raise ErroWebhook("status não estruturado")
                pid=item.get("id")
                tipo=item.get("status")
                if not isinstance(pid,str) or not _PID.fullmatch(pid) or tipo not in _STATES:
                    raise ErroWebhook("ID ou estado do evento inválido")
                if tipo=="delivered":
                    stamp=item.get("timestamp")
                    if not isinstance(stamp,str) or not re.fullmatch(r"\d{10,13}",stamp):
                        raise ErroWebhook("timestamp de entrega ausente ou inválido")
                    try:
                        hora=datetime.fromtimestamp(int(stamp),tz=timezone.utc).isoformat()
                    except (OverflowError,ValueError,OSError) as exc:
                        raise ErroWebhook("timestamp de entrega fora de intervalo") from exc
                else:
                    hora=datetime.now(timezone.utc).isoformat()
                eventos.append((pid,tipo,hora))
                if len(eventos)>1000:
                    raise ErroWebhook("notificação com excesso de status")
    return eventos


def aplicar_webhook_unificado(
    db: sqlite3.Connection, *, raw_body: bytes,
    signature: str, app_secret: str,
) -> dict:
    """Assinatura válida + protocolo reconhecido -> commit único nos dois ledgers."""
    verificar_assinatura(raw_body=raw_body,signature=signature,app_secret=app_secret)
    eventos=_eventos(raw_body)  # validar tudo ANTES de iniciar a transação
    preparar_recibos(db)
    _whatsapp_esquema(db)
    db.execute("BEGIN IMMEDIATE")
    aplicados=0
    ignorados=0
    try:
        for pid,tipo,quando in eventos:
            can=db.execute("""SELECT canal FROM nivon_recibos_canonicos
                WHERE provider_message_id=?""",(pid,)).fetchone()
            if not can:
                ignorados+=1
                continue
            if can[0]=="BRIEFING":
                # O legado só reconhece delivered como prova de entrega.
                if tipo!="delivered":
                    ignorados+=1
                    continue
                row=db.execute("""SELECT status FROM briefing_outbox
                    WHERE provider_message_id=?""",(pid,)).fetchone()
                if row is None:
                    raise ErroWebhook("recibo canônico sem vínculo legado")
                if row[0]=="DELIVERED":
                    ignorados+=1
                    continue
                if row[0]!="ACCEPTED":
                    raise ErroWebhook("entrega sem aceite de briefing")
                atualizado=aplicar_recibo_na_transacao(
                    db,provider_message_id=pid,estado="ENTREGUE",quando=quando,
                )
                if not atualizado["reconhecido"] or not atualizado["atualizado"]:
                    raise ErroWebhook("estado canônico contradiz briefing")
                db.execute("""UPDATE briefing_outbox
                    SET status='DELIVERED',confirmado_utc=?
                    WHERE provider_message_id=? AND status='ACCEPTED'""",
                    (quando,pid))
                aplicados+=1
            elif can[0]=="WHATSAPP":
                row=db.execute("""SELECT estado FROM nivon_envios
                    WHERE provider_message_id=?""",(pid,)).fetchone()
                if row is None:
                    raise ErroWebhook("recibo canônico sem intenção WhatsApp")
                novo=WEBHOOK_ESTADOS[tipo]
                atualizado=aplicar_recibo_na_transacao(
                    db,provider_message_id=pid,estado=novo,quando=quando,
                )
                if not atualizado["reconhecido"]:
                    raise ErroWebhook("estado canônico de WhatsApp ausente")
                if not atualizado["atualizado"]:
                    ignorados+=1
                    continue
                db.execute("""UPDATE nivon_envios
                    SET estado=?,atualizado_em=?
                    WHERE provider_message_id=?""",(novo,quando,pid))
                aplicados+=1
            else:
                raise ErroWebhook("canal desconhecido em recibo")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"estado":"WEBHOOK_UNIFICADO_ASSINADO_SEM_ENVIO",
            "recebidos":len(eventos),"aplicados":aplicados,
            "ignorados":ignorados,"homologado_operacional":False}
