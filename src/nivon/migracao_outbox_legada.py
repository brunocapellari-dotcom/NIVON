"""Migração OFFLINE das outboxes legadas: inventário, quarentena, sem promoção.

Nunca inventa opt-in, ACK, recibo entregue, direitos, nem cria novo envio.
Registros de histórico ficam imutáveis; somente fingerprints opacos entram na
quarentena, que é repetível e detecta alterações após sua captura.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import date

from .outbox_recibos import preparar_recibos
from .outbox_unificada import ErroControleEnvio

_HEX = re.compile(r"[a-f0-9]{64}\Z")
_ESTADOS_BRIEFING = {"PENDING","RESERVED","ACCEPTED","DELIVERED","BLOCKED"}
_ESTADOS_WHATSAPP = {"PREPARADO","ENVIO_INDETERMINADO","ACEITO_PROVEDOR",
                     "ENVIADO","ENTREGUE","LIDO","FALHOU"}


def _tabela(db: sqlite3.Connection, nome: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                      (nome,)).fetchone() is not None


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _linha(canal: str, id_original: str, dia: str, destino: str,
           estado: str, provider: str | None, estados: set[str]) -> dict:
    if not isinstance(destino,str) or not _HEX.fullmatch(destino):
        raise ErroControleEnvio("legacy: HMAC de destinatário inválido")
    try:
        if date.fromisoformat(dia).isoformat()!=dia:
            raise ValueError("non-canonical")
    except (ValueError,TypeError,AttributeError) as exc:
        raise ErroControleEnvio("legacy: data inválida") from exc
    if estado not in estados:
        raise ErroControleEnvio("legacy: estado não reconhecido")
    if not isinstance(id_original,str) or len(id_original)>256 or not id_original:
        raise ErroControleEnvio("legacy: identificador inválido")
    if provider is not None and (not isinstance(provider,str) or len(provider)>256):
        raise ErroControleEnvio("legacy: ID de provedor inválido")
    return {"registro_sha256":_sha(canal+"|"+id_original),
            "dia_local":dia,"destinatario_hmac":destino,
            "canal":canal,"estado_legado":estado,
            "provider_sha256":_sha(provider) if provider else None}


def _ler_legado(db: sqlite3.Connection) -> list[dict]:
    registros=[]
    if _tabela(db,"briefing_outbox"):
        for r in db.execute("""SELECT id,dia_local,destinatario_hmac,status,
              provider_message_id FROM briefing_outbox ORDER BY id"""):
            registros.append(_linha("BRIEFING",str(r[0]),r[1],r[2],r[3],r[4],
                                    _ESTADOS_BRIEFING))
    if _tabela(db,"nivon_envios"):
        for r in db.execute("""SELECT idempotency_key,edicao,destinatario_hmac,
              estado,provider_message_id FROM nivon_envios ORDER BY idempotency_key"""):
            registros.append(_linha("WHATSAPP",r[0],r[1],r[2],r[3],r[4],
                                    _ESTADOS_WHATSAPP))
    return registros


def _contexto(db: sqlite3.Connection, rows: list[dict]) -> list[dict]:
    dias=Counter((r["dia_local"],r["destinatario_hmac"]) for r in rows)
    providers=Counter(r["provider_sha256"] for r in rows if r["provider_sha256"])
    consentimentos={}
    reservas={}
    if _tabela(db,"nivon_consentimentos"):
        consentimentos=dict(db.execute(
            "SELECT destinatario_hmac,estado FROM nivon_consentimentos"))
    if _tabela(db,"nivon_reservas_canonicas"):
        reservas={(r[0],r[1]):r[2] for r in db.execute(
            "SELECT dia_local,destinatario_hmac,canal FROM nivon_reservas_canonicas")}
    result=[]
    for reg in rows:
        k=(reg["dia_local"],reg["destinatario_hmac"])
        estado_consent=consentimentos.get(reg["destinatario_hmac"])
        if dias[k]>1:
            motivo="DUPLICIDADE_DIA_DESTINATARIO"
        elif reg["provider_sha256"] and providers[reg["provider_sha256"]]>1:
            motivo="PROVEDOR_REUTILIZADO"
        elif estado_consent is None:
            motivo="CONSENTIMENTO_NAO_COMPROVADO"
        elif estado_consent=="REVOGADO":
            motivo="CONSENTIMENTO_REVOGADO"
        elif reservas.get(k) and reservas[k]!=reg["canal"]:
            motivo="RESERVA_CROSS_CANAL_DIVERGENTE"
        else:
            motivo="HISTORICO_SEM_ATESTACAO_EXTERNA"
        result.append({**reg,"motivo":motivo,
                       "promocao_permitida":False,"envio_autorizado":False})
    return result


def _montar_plano(db: sqlite3.Connection) -> dict:
    """Snapshot coerente; chamar de fora ou DENTRO de BEGIN IMMEDIATE."""
    rows=_contexto(db,_ler_legado(db))
    grupos=dict(sorted(Counter(r["motivo"] for r in rows).items()))
    return {"status":"QUARENTENA_SOMENTE_SEM_PROMOCAO",
            "total":len(rows),"grupos":grupos,
            "registros":rows,"envios_novos":0,
            "publicacao_autorizada":False}

def planejar_migracao(db: sqlite3.Connection) -> dict:
    """Read-only inclusive em bases sem tabelas canônicas."""
    if db.in_transaction:
        raise ErroControleEnvio("inventário exige conexão fora de transação")
    return _montar_plano(db)


def hash_snapshot_legado(db: sqlite3.Connection) -> str:
    """Assina conteúdo dos legados sem expor PII; não é prova externa."""
    rows=_ler_legado(db)
    data=json.dumps(rows,sort_keys=True,ensure_ascii=False,
                    separators=(",",":")).encode("utf-8")
    import hashlib
    return hashlib.sha256(data).hexdigest()



def _preparar_quarentena(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_quarentena_legado (
        registro_sha256 TEXT PRIMARY KEY,
        dia_local TEXT NOT NULL,
        destinatario_hmac TEXT NOT NULL,
        canal TEXT NOT NULL,
        estado_legado TEXT NOT NULL,
        provider_sha256 TEXT,
        motivo TEXT NOT NULL,
        fingerprint_sha256 TEXT NOT NULL,
        registrado_utc TEXT NOT NULL,
        estado_revisao TEXT NOT NULL DEFAULT 'PENDENTE'
          CHECK(estado_revisao='PENDENTE')
    )""")


def _fingerprint(row: dict) -> str:
    blob=json.dumps({k:row[k] for k in (
        "registro_sha256","dia_local","destinatario_hmac","canal",
        "estado_legado","provider_sha256","motivo")},
        sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def registrar_quarentena(
    db: sqlite3.Connection, *, autorizar_staging: bool = False,
    registrado_em: str, snapshot_legado_esperado: str | None = None,
) -> dict:
    """Captura legados SOB BEGIN IMMEDIATE; não promove nem envia."""
    if autorizar_staging is not True:
        raise PermissionError("quarentena exige autorização explícita do chamador")
    from .outbox_unificada import _tempo
    ts=_tempo(registrado_em)
    db.execute("BEGIN IMMEDIATE")
    novos=0
    try:
        if snapshot_legado_esperado is not None:
            if (not isinstance(snapshot_legado_esperado,str)
                    or not re.fullmatch(r"[a-f0-9]{64}",snapshot_legado_esperado)
                    or hash_snapshot_legado(db)!=snapshot_legado_esperado):
                raise ErroControleEnvio(
                    "fontes legadas alteradas desde o backup pré-migração"
                )
        plano=_montar_plano(db)
        _preparar_quarentena(db)  # DDL SQLite também reverte se falhar a migração.
        for row in plano["registros"]:
            fp=_fingerprint(row)
            existente=db.execute("""SELECT fingerprint_sha256
                FROM nivon_quarentena_legado WHERE registro_sha256=?""",
                (row["registro_sha256"],)).fetchone()
            if existente:
                if existente[0]!=fp:
                    raise ErroControleEnvio("registro legado alterado após a captura")
                continue
            db.execute("""INSERT INTO nivon_quarentena_legado
                (registro_sha256,dia_local,destinatario_hmac,canal,
                 estado_legado,provider_sha256,motivo,fingerprint_sha256,
                 registrado_utc) VALUES (?,?,?,?,?,?,?,?,?)""",
                (row["registro_sha256"],row["dia_local"],
                 row["destinatario_hmac"],row["canal"],row["estado_legado"],
                 row["provider_sha256"],row["motivo"],fp,ts))
            novos+=1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"estado":"QUARENTENA_REGISTRADA_SEM_PROMOCAO",
            "registrados":novos,"ja_existentes":plano["total"]-novos,
            "total":plano["total"],"envios_executados":0,
            "aceites_gerados":0,"entregas_geradas":0}
