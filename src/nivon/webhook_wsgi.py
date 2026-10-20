"""Entrada WSGI isolada para verificacao e eventos de WhatsApp Cloud API.

Somente o reverse proxy autorizado pode expor o app; instalar/rodar o módulo
não cria serviço. Requer variáveis de ambiente de segredo e banco persistente.
"""
from __future__ import annotations

import hmac
from contextlib import closing
import os
import re
import sqlite3
from urllib.parse import parse_qs

from .outbox_briefing import abrir_outbox, ErroOutbox
from .whatsapp_webhook import aplicar_webhook_entregas, ErroWebhook

_MAX = 256_000
_PATH = "/webhooks/whatsapp"


def _response(start_response, status: str, body: bytes):
    start_response(status, [
        ("Content-Type","text/plain; charset=utf-8"),
        ("Content-Length",str(len(body))),
        ("Cache-Control","no-store"),
        ("X-Content-Type-Options","nosniff"),
    ])
    return [body]


def app(environ: dict, start_response):
    """GET challenge e POST status; nenhuma rota de envio é exposta."""
    if environ.get("PATH_INFO") != _PATH:
        return _response(start_response,"404 Not Found",b"not found")
    method=environ.get("REQUEST_METHOD")
    if method not in {"GET","POST"}:
        return _response(start_response,"405 Method Not Allowed",b"method not allowed")
    verify=os.environ.get("NIVON_META_VERIFY_TOKEN")
    secret=os.environ.get("NIVON_META_APP_SECRET")
    dbpath=os.environ.get("NIVON_OUTBOX_PATH")
    if not verify or not secret or len(secret.encode()) < 32 or not dbpath:
        return _response(start_response,"503 Service Unavailable",b"not configured")
    if method=="GET":
        try:
            query=parse_qs(environ.get("QUERY_STRING",""),
                           keep_blank_values=True,max_num_fields=8)
            if any(len(v)!=1 for v in query.values()):
                raise ValueError("duplicated parameter")
            mode=query.get("hub.mode",[None])[0]
            token=query.get("hub.verify_token",[None])[0]
            challenge=query.get("hub.challenge",[None])[0]
            if (mode!="subscribe" or not isinstance(token,str) or
                not hmac.compare_digest(token,verify) or
                not isinstance(challenge,str) or
                not re.fullmatch(r"\d{1,80}",challenge)):
                raise ValueError("challenge invalid")
        except (ValueError,TypeError):
            return _response(start_response,"403 Forbidden",b"forbidden")
        return _response(start_response,"200 OK",challenge.encode("ascii"))
    if environ.get("CONTENT_TYPE","").split(";",1)[0].strip().lower() != "application/json":
        return _response(start_response,"415 Unsupported Media Type",b"invalid media type")
    try:
        n=int(environ.get("CONTENT_LENGTH","-1"))
    except (ValueError,TypeError):
        return _response(start_response,"411 Length Required",b"invalid length")
    if not 0<n<=_MAX:
        return _response(start_response,"413 Content Too Large",b"invalid length")
    stream=environ.get("wsgi.input")
    if stream is None:
        return _response(start_response,"400 Bad Request",b"missing body")
    raw=stream.read(n)
    if not isinstance(raw,bytes) or len(raw)!=n:
        return _response(start_response,"400 Bad Request",b"invalid body")
    signature=environ.get("HTTP_X_HUB_SIGNATURE_256","")
    try:
        with closing(abrir_outbox(dbpath)) as db:
            aplicar_webhook_entregas(
                db,raw_body=raw,signature=signature,app_secret=secret)
    except PermissionError:
        return _response(start_response,"403 Forbidden",b"forbidden")
    except ErroOutbox:
        return _response(start_response,"503 Service Unavailable",b"unavailable")
    except (ErroWebhook,ValueError):
        return _response(start_response,"400 Bad Request",b"invalid event")
    except (OSError,RuntimeError,sqlite3.DatabaseError):
        return _response(start_response,"503 Service Unavailable",b"unavailable")
    return _response(start_response,"200 OK",b"acknowledged")
