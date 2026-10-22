"""Ledger CANÔNICO de aceite e recibos de entrega dos dois canais NIVON.

Apenas estado local offline; não autentica webhooks, não envia e não concede
autoridade aos dados dos provedores. Chamadores autenticam ACK/assinatura e
mantêm transação BEGIN IMMEDIATE envolvendo legado + registro canônico.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from .outbox_unificada import ErroControleEnvio, _tempo, _schema as _reservas_schema

_ID = re.compile(r"[A-Za-z0-9_.:@-]{1,256}\Z")
_CANAIS = frozenset(("BRIEFING", "WHATSAPP"))
_ESTADOS = frozenset(("ACEITO_PROVEDOR", "ENVIADO", "ENTREGUE", "LIDO", "FALHOU"))
_ORDEM = {"ACEITO_PROVEDOR": 0, "ENVIADO": 1, "ENTREGUE": 2, "LIDO": 3}


def preparar_recibos(db: sqlite3.Connection) -> None:
    """Migração não destrutiva; chamar fora de qualquer transação."""
    if db.in_transaction:
        raise ErroControleEnvio("esquema de recibos exige conexão sem transação")
    _reservas_schema(db)
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_recibos_canonicos (
        dia_local TEXT NOT NULL,
        destinatario_hmac TEXT NOT NULL,
        canal TEXT NOT NULL CHECK(canal IN ('BRIEFING','WHATSAPP')),
        intencao_id TEXT NOT NULL,
        provider_message_id TEXT NOT NULL UNIQUE,
        estado TEXT NOT NULL CHECK(estado IN
            ('ACEITO_PROVEDOR','ENVIADO','ENTREGUE','LIDO','FALHOU')),
        aceite_utc TEXT NOT NULL,
        atualizado_utc TEXT NOT NULL,
        entregue_utc TEXT,
        PRIMARY KEY(dia_local,destinatario_hmac),
        FOREIGN KEY(dia_local,destinatario_hmac)
            REFERENCES nivon_reservas_canonicas(dia_local,destinatario_hmac)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_eventos_recibo (
        provider_message_id TEXT NOT NULL,
        estado TEXT NOT NULL,
        visto_utc TEXT NOT NULL,
        PRIMARY KEY(provider_message_id,estado),
        FOREIGN KEY(provider_message_id)
            REFERENCES nivon_recibos_canonicos(provider_message_id)
    )""")


def _validar_id(provider_message_id: str) -> str:
    if not isinstance(provider_message_id, str) or not _ID.fullmatch(provider_message_id):
        raise ErroControleEnvio("identificador de provedor inválido")
    return provider_message_id


def _checar_transacao(db: sqlite3.Connection) -> None:
    if not db.in_transaction:
        raise ErroControleEnvio("atualização canônica exige transação iniciada pelo chamador")


def vincular_aceite_na_transacao(
    db: sqlite3.Connection, *, canal: str, intencao_id: str,
    provider_message_id: str, quando: str,
) -> dict:
    """Vincula ACK ao slot existente; sem inferir entrega ou permitir trocar ID."""
    _checar_transacao(db)
    if canal not in _CANAIS or not isinstance(intencao_id, str) or not intencao_id:
        raise ErroControleEnvio("canal/intenção não reconhecidos")
    pid = _validar_id(provider_message_id)
    ts = _tempo(quando)
    slot = db.execute("""SELECT dia_local,destinatario_hmac
        FROM nivon_reservas_canonicas
        WHERE canal=? AND intencao_id=?""", (canal, intencao_id)).fetchone()
    if slot is None:
        raise ErroControleEnvio("aceite sem reserva canônica anterior")
    existe = db.execute("""SELECT provider_message_id,estado
        FROM nivon_recibos_canonicos
        WHERE dia_local=? AND destinatario_hmac=?""", (slot[0], slot[1])).fetchone()
    if existe:
        if existe[0] != pid:
            raise ErroControleEnvio("mesma reserva não admite segundo ID do provedor")
        return {"novo": False, "estado": existe[1]}
    try:
        db.execute("""INSERT INTO nivon_recibos_canonicos
            (dia_local,destinatario_hmac,canal,intencao_id,provider_message_id,
             estado,aceite_utc,atualizado_utc)
             VALUES (?,?,?,?,?,'ACEITO_PROVEDOR',?,?)""",
             (slot[0], slot[1], canal, intencao_id, pid, ts, ts))
        db.execute("""INSERT INTO nivon_eventos_recibo
            (provider_message_id,estado,visto_utc)
            VALUES (?,'ACEITO_PROVEDOR',?)""", (pid,ts))
    except sqlite3.IntegrityError as exc:
        raise ErroControleEnvio("ID de provedor já associado a outro destinatário/edição") from exc
    return {"novo": True, "estado": "ACEITO_PROVEDOR"}


def aplicar_recibo_na_transacao(
    db: sqlite3.Connection, *, provider_message_id: str,
    estado: str, quando: str,
) -> dict:
    """Só chamada depois de autenticação Meta ou reconciliação humana confiável.

    'sent' é ENVIADO, nunca ENTREGA. Eventos fora de ordem não rebaixam.
    'failed' é terminal antes de entrega, nunca desfaz entrega ou leitura.
    """
    _checar_transacao(db)
    pid = _validar_id(provider_message_id)
    if estado not in _ESTADOS or estado == "ACEITO_PROVEDOR":
        raise ErroControleEnvio("recibo sem estado externo admissível")
    ts = _tempo(quando)
    row = db.execute("""SELECT estado,entregue_utc FROM nivon_recibos_canonicos
        WHERE provider_message_id=?""", (pid,)).fetchone()
    if not row:
        return {"reconhecido": False, "atualizado": False}
    atual,entregue = row
    if (atual == "FALHOU"
            or (estado == "FALHOU" and atual in ("ENTREGUE","LIDO"))
            or (estado != "FALHOU" and _ORDEM.get(estado, -1) <= _ORDEM.get(atual, -1))):
        return {"reconhecido": True, "atualizado": False, "estado": atual}
    recebido = (ts if estado == "ENTREGUE" and entregue is None else entregue)
    db.execute("""UPDATE nivon_recibos_canonicos
        SET estado=?,atualizado_utc=?,entregue_utc=?
        WHERE provider_message_id=?""", (estado,ts,recebido,pid))
    db.execute("""INSERT OR IGNORE INTO nivon_eventos_recibo
        (provider_message_id,estado,visto_utc) VALUES (?,?,?)""",(pid,estado,ts))
    return {"reconhecido": True, "atualizado": True, "estado": estado}


def consultar_recibo(db: sqlite3.Connection, *, provider_message_id: str) -> dict:
    preparar_recibos(db)
    row = db.execute("""SELECT dia_local,canal,estado,aceite_utc,atualizado_utc,
        entregue_utc FROM nivon_recibos_canonicos
        WHERE provider_message_id=?""", (_validar_id(provider_message_id),)).fetchone()
    if row is None:
        raise ErroControleEnvio("recibo ausente de ledger canônico")
    return dict(zip(
        ("dia_local","canal","estado","aceite_utc","atualizado_utc","entregue_utc"),row
    ))
