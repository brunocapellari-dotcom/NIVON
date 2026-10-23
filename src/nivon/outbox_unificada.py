"""Registro canônico transacional de consentimento e reserva diária do NIVON.

Sem rede, envio, contatos em claro, modelos, publicação ou credenciais gravadas.
As duas outboxes legadas DEVEM usar a MESMA conexão/arquivo SQLite para reservar.
HMAC autentica uma decisão declarada pelo operador; comprovação independente do
opt-in e política de revogação são pré-requisitos externos antes de produção.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
from datetime import date, datetime, timezone

HASH_RE = re.compile(r"[a-f0-9]{64}\Z")
EVIDENCIA_RE = re.compile(r"[A-Za-z0-9_.:-]{12,160}\Z")
CANAIS = frozenset({"BRIEFING", "WHATSAPP"})
ACOES = frozenset({"CONCEDER", "REVOGAR"})


class ErroControleEnvio(ValueError):
    pass


def _hash(digest: str) -> str:
    if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
        raise ErroControleEnvio("destinatário deve ser HMAC hex opaco")
    return digest


def _tempo(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ErroControleEnvio("instante assinado inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroControleEnvio("instante deve ter fuso")
    return dt.astimezone(timezone.utc).isoformat()


def _dia(value: str) -> str:
    try:
        d = date.fromisoformat(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ErroControleEnvio("edição exige data real") from exc
    if value != d.isoformat():
        raise ErroControleEnvio("dia da edição não canônico")
    return value


def _schema(db: sqlite3.Connection) -> None:
    if db.in_transaction:
        raise ErroControleEnvio("esquema só pode ser preparado fora de transação")
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_consentimentos (
        destinatario_hmac TEXT PRIMARY KEY,
        estado TEXT NOT NULL CHECK (estado IN ('CONCEDIDO','REVOGADO')),
        evidencia_id TEXT NOT NULL,
        decisao_utc TEXT NOT NULL,
        assinatura_sha256 TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_reservas_canonicas (
        dia_local TEXT NOT NULL,
        destinatario_hmac TEXT NOT NULL,
        canal TEXT NOT NULL CHECK (canal IN ('BRIEFING','WHATSAPP')),
        intencao_id TEXT NOT NULL,
        reservada_utc TEXT NOT NULL,
        estado TEXT NOT NULL CHECK (estado IN ('RESERVADA','BLOQUEADA_REVOGACAO')),
        PRIMARY KEY (dia_local, destinatario_hmac),
        UNIQUE (canal, intencao_id),
        FOREIGN KEY (destinatario_hmac)
            REFERENCES nivon_consentimentos(destinatario_hmac)
    )""")


def mensagem_de_prova(*, acao: str, destinatario_hmac: str,
                      evidencia_id: str, em: str) -> bytes:
    if acao not in ACOES or not isinstance(evidencia_id, str) or not EVIDENCIA_RE.fullmatch(evidencia_id):
        raise ErroControleEnvio("decisão/evidência não permitida")
    return ("NIVON|CONSENTIMENTO|V1|" + acao + "|" + _hash(destinatario_hmac)
            + "|" + evidencia_id + "|" + _tempo(em)).encode("utf-8")


def registrar_decisao_consentimento(
    db: sqlite3.Connection, *, acao: str, destinatario_hmac: str,
    evidencia_id: str, em: str, assinatura: str, chave_verificacao: bytes,
) -> dict:
    """Prova HMAC gerada FORA deste módulo; não atesta identidade do signatário."""
    payload = mensagem_de_prova(acao=acao, destinatario_hmac=destinatario_hmac,
                               evidencia_id=evidencia_id, em=em)
    if not isinstance(chave_verificacao, bytes) or len(chave_verificacao) < 32:
        raise ErroControleEnvio("chave de autoridade curta ou indisponível")
    if not isinstance(assinatura, str) or not HASH_RE.fullmatch(assinatura):
        raise PermissionError("prova de consentimento ausente")
    esperado = hmac.new(chave_verificacao, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperado, assinatura):
        raise PermissionError("prova assinada inválida")
    ts = _tempo(em)
    # Prova autêntica com carimbo de tempo futuro não representa autorização
    # vigente. Rejeitar na ingestão para não envenenar o ledger canônico.
    if datetime.fromisoformat(ts) > datetime.now(timezone.utc):
        raise ErroControleEnvio("decisão de consentimento futura não é vigente")
    _schema(db)
    db.execute("BEGIN IMMEDIATE")
    try:
        anterior = db.execute(
            "SELECT estado, evidencia_id, decisao_utc FROM nivon_consentimentos "
            "WHERE destinatario_hmac=?", (destinatario_hmac,),
        ).fetchone()
        if anterior:
            if ts < anterior[2]:
                raise ErroControleEnvio("decisão anterior não pode suplantar a atual")
            if anterior[0] == "REVOGADO":
                if acao != "REVOGAR":
                    raise PermissionError("revogação terminal; nova adesão requer processo separado")
                if ts == anterior[2] and evidencia_id != anterior[1]:
                    raise ErroControleEnvio("revogação conflitante")
            if anterior[0] == "CONCEDIDO" and acao == "CONCEDER":
                if evidencia_id != anterior[1] or ts != anterior[2]:
                    raise ErroControleEnvio("renovação exige procedimento independente")
        estado = "REVOGADO" if acao == "REVOGAR" else "CONCEDIDO"
        db.execute("""INSERT INTO nivon_consentimentos
            (destinatario_hmac,estado,evidencia_id,decisao_utc,assinatura_sha256)
            VALUES (?,?,?,?,?)
            ON CONFLICT(destinatario_hmac) DO UPDATE SET
                estado=excluded.estado,
                evidencia_id=excluded.evidencia_id,
                decisao_utc=excluded.decisao_utc,
                assinatura_sha256=excluded.assinatura_sha256""",
            (destinatario_hmac, estado, evidencia_id, ts, assinatura))
        if estado == "REVOGADO":
            db.execute("""UPDATE nivon_reservas_canonicas
                SET estado='BLOQUEADA_REVOGACAO'
                WHERE destinatario_hmac=? AND estado='RESERVADA'""",
                (destinatario_hmac,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"destinatario_hmac": destinatario_hmac,
            "consentimento": estado, "evidencia_id": evidencia_id,
            "comprovacao_externa_homologada": False, "envio_autorizado": False}


def _consentimento_atual(
    db: sqlite3.Connection, destinatario_hmac: str, *,
    corte: str | None = None,
) -> None:
    # O estado atual não basta: uma concessão posterior ao corte NÃO autoriza
    # uma reserva retrospectiva. Esta validação também protege o pre-POST.
    row = db.execute(
        "SELECT estado, decisao_utc FROM nivon_consentimentos "
        "WHERE destinatario_hmac=?",
        (_hash(destinatario_hmac),),
    ).fetchone()
    instante = datetime.now(timezone.utc) if corte is None else datetime.fromisoformat(_tempo(corte))
    if (row is None or row[0] != "CONCEDIDO"
            or datetime.fromisoformat(row[1]) > instante
            or datetime.fromisoformat(row[1]) > datetime.now(timezone.utc)):
        raise PermissionError("consentimento ausente, revogado ou não vigente no corte")


def reservar_na_transacao(
    db: sqlite3.Connection, *, dia_local: str, destinatario_hmac: str,
    canal: str, intencao_id: str, agora: str,
) -> None:
    """Chamador já abriu BEGIN IMMEDIATE. Falha atomica se outro canal reservou."""
    if not db.in_transaction:
        raise ErroControleEnvio("reserva exige transação de escrita aberta")
    _dia(dia_local)
    _hash(destinatario_hmac)
    if canal not in CANAIS or not isinstance(intencao_id, str) or not 1 <= len(intencao_id) <= 160:
        raise ErroControleEnvio("canal/intenção inválidos")
    ts = _tempo(agora)
    _consentimento_atual(db, destinatario_hmac, corte=ts)
    try:
        db.execute("""INSERT INTO nivon_reservas_canonicas
            (dia_local,destinatario_hmac,canal,intencao_id,reservada_utc,estado)
            VALUES (?,?,?,?,?,'RESERVADA')""",
            (dia_local, destinatario_hmac, canal, intencao_id, ts))
    except sqlite3.IntegrityError as exc:
        raise ErroControleEnvio(
            "destinatário/edição já reservado por qualquer canal; sem segundo POST"
        ) from exc


def verificar_consentimento_pre_post(
    db: sqlite3.Connection, *, dia_local: str, destinatario_hmac: str,
    canal: str, intencao_id: str,
) -> None:
    """Checagem antes do POST. NÃO elimina a corrida de revogação no provedor."""
    _schema(db)
    row = db.execute("""SELECT estado, reservada_utc FROM nivon_reservas_canonicas
        WHERE dia_local=? AND destinatario_hmac=? AND canal=? AND intencao_id=?""",
        (_dia(dia_local), destinatario_hmac, canal, intencao_id)).fetchone()
    if row is None or row[0] != "RESERVADA":
        raise PermissionError("reserva central ausente, revogada ou divergente")
    # Nunca revalidar um envio anterior com consentimento concedido depois
    # da reserva, mesmo que a tabela de decisões seja alterada externamente.
    _consentimento_atual(db, destinatario_hmac, corte=row[1])
