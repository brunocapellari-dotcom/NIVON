"""Outbox diário do briefing: idempotência e estados de entrega sem envio real.

Não armazena texto ou telefone; só aceita destinatário como HMAC SHA-256 opaco.
Integração futura deve guardar corpo cifrado em store persistente, reconciliar
ACKs de webhook autenticados e só marcar entregue após confirmação externa.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from .outbox_unificada import _schema as _controle_esquema, reservar_na_transacao


class ErroOutbox(ValueError):
    pass


def abrir_outbox(path: str | Path = ":memory:") -> sqlite3.Connection:
    if str(path) != ":memory:":
        p=Path(path)
        if p.is_symlink() or not p.parent.is_dir():
            raise ErroOutbox("caminho de outbox não autorizado")
    db=sqlite3.connect(str(path),timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS briefing_outbox (
      id INTEGER PRIMARY KEY,
      dia_local TEXT NOT NULL,
      destinatario_hmac TEXT NOT NULL,
      texto_sha256 TEXT NOT NULL,
      agendado_utc TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN (
        'PENDING','RESERVED','ACCEPTED','DELIVERED','BLOCKED')),
      reservacao TEXT,
      provider_message_id TEXT,
      confirmado_utc TEXT,
      UNIQUE(dia_local,destinatario_hmac),
      UNIQUE(provider_message_id)
    );
    """)
    return db


def _hash(value: str) -> str:
    if not isinstance(value,str) or not re.fullmatch(r"[0-9a-f]{64}",value):
        raise ErroOutbox("SHA-256/HMAC inválido")
    return value


def _instante(value: str) -> str:
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    except (TypeError,ValueError) as exc:
        raise ErroOutbox("hora inválida") from exc
    if dt.tzinfo is None:
        raise ErroOutbox("hora sem fuso")
    return dt.astimezone(timezone.utc).isoformat()


def agendar_briefing(db: sqlite3.Connection, *, dia_local: str,
                     destinatario_hmac: str, briefing: dict,
                     agora: str, auditoria_aprovada: bool = False) -> dict:
    """Apenas prepara a saída. Não permite custo, comunicação ou reenvio."""
    if auditoria_aprovada is not True:
        raise PermissionError("auditoria humana/determinística não aprovada")
    _hash(destinatario_hmac)
    try:
        data=date.fromisoformat(dia_local)
    except (ValueError,TypeError) as exc:
        raise ErroOutbox("dia local inválido") from exc
    if data.isoformat()!=dia_local:
        raise ErroOutbox("data não canônica")
    if briefing.get("status")!="PREPARADO_SEM_ENVIO":
        raise ErroOutbox("briefing em estado inválido")
    digest=_hash(briefing.get("sha256"))
    if not isinstance(briefing.get("texto"),str) or not briefing["texto"]:
        raise ErroOutbox("texto não encontrado")
    import hashlib
    if hashlib.sha256(briefing["texto"].encode("utf-8")).hexdigest()!=digest:
        raise ErroOutbox("hash editorial adulterado")
    ts=_instante(agora)
    with db:
        exists=db.execute("""SELECT * FROM briefing_outbox
           WHERE dia_local=? AND destinatario_hmac=?""",
           (dia_local,destinatario_hmac)).fetchone()
        if exists is not None:
            if exists["texto_sha256"]!=digest:
                raise ErroOutbox("briefing diário já agendado; correção exige procedimento auditado")
            return {"id":exists["id"],"nova":False,"status":exists["status"]}
        ident=db.execute("""INSERT INTO briefing_outbox
          (dia_local,destinatario_hmac,texto_sha256,agendado_utc,status)
          VALUES (?,?,?,?,'PENDING')""",
          (dia_local,destinatario_hmac,digest,ts)).lastrowid
    return {"id":ident,"nova":True,"status":"PENDING"}


def reservar_para_entrega(db: sqlite3.Connection, *, id: int) -> dict:
    """Reserva atomicamente a edição no ledger comum e no legado.

    Falha fechado se não houver consentimento assinado ou se o outro canal
    reservou o dia/destinatário. Sem POST nem retry automático.
    """
    token=secrets.token_hex(24)
    _controle_esquema(db)
    db.execute("BEGIN IMMEDIATE")
    try:
        row=db.execute("""SELECT dia_local,destinatario_hmac,texto_sha256,status
            FROM briefing_outbox WHERE id=?""",(id,)).fetchone()
        if row is None or row["status"]!="PENDING":
            raise ErroOutbox("reserva duplicada ou briefing não elegível")
        reservar_na_transacao(
            db,dia_local=row["dia_local"],
            destinatario_hmac=row["destinatario_hmac"],
            canal="BRIEFING",intencao_id=str(id),
            agora=datetime.now(timezone.utc).isoformat(),
        )
        result=db.execute("""UPDATE briefing_outbox
            SET status='RESERVED',reservacao=?
            WHERE id=? AND status='PENDING'""",(token,id))
        if result.rowcount!=1:
            raise ErroOutbox("reserva simultânea ou briefing alterado")
        digest=row["texto_sha256"]
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"id":id,"token":token,"sha256":digest,
            "status":"RESERVED_SEM_ENVIO"}


def registrar_aceite(db: sqlite3.Connection, *, id: int, token: str,
                    provider_message_id: str) -> dict:
    """ACCEPTED significa que provedor recebeu requisição, não que entregou."""
    if not isinstance(provider_message_id,str) or not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,256}",provider_message_id):
        raise ErroOutbox("ID de provedor inválido")
    with db:
        r=db.execute("""UPDATE briefing_outbox SET status='ACCEPTED',provider_message_id=?
          WHERE id=? AND status='RESERVED' AND reservacao=?""",
          (provider_message_id,id,token))
        if r.rowcount!=1:
            raise ErroOutbox("ID/nonce não está reservado")
    return {"id":id,"status":"ACCEPTED_AGUARDA_DELIVERY_ACK"}


def confirmar_entrega(db: sqlite3.Connection, *, provider_message_id: str,
                      autenticado: bool = False, quando: str) -> dict:
    """Somente o adaptador que VERIFICOU assinatura externa pode chamar."""
    if autenticado is not True:
        raise PermissionError("webhook sem autenticação/assinatura verificada")
    ts=_instante(quando)
    with db:
        result=db.execute("""UPDATE briefing_outbox
          SET status='DELIVERED',confirmado_utc=?
          WHERE provider_message_id=? AND status='ACCEPTED'""",
          (ts,provider_message_id))
        if result.rowcount!=1:
            raise ErroOutbox("recibo não reconhecido ou duplicado")
    return {"status":"ENTREGUE_COM_ACK_AUTENTICADO"}
