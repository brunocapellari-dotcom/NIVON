"""Checkpoints assinados de frescor do registro de revogações ANP/LPC.

Sem rede, segredos de produção ou aprovação automática. Um checkpoint
verifica a DECLARAÇÃO de uma autoridade externa, não a completude real
do serviço emissor (que exige homologação independente).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import re
import sqlite3
from typing import Mapping

_PREFIX = b"NIVON_ANP_LPC_REVOGACOES_CHECKPOINT_V1\x00"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_COLUNAS = (
    "revogacao_id", "sha", "dominio", "aprovacao_id", "emissor_id",
    "motivo_codigo", "emitido_em", "recebido_em", "assinatura_sha256",
)


class ErroCheckpointANP(PermissionError):
    pass


def _tempo(v: object, campo: str) -> datetime:
    if not isinstance(v, str):
        raise ErroCheckpointANP(f"{campo}: timestamp com timezone obrigatório")
    try:
        valor = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroCheckpointANP(f"{campo}: timestamp inválido") from exc
    if valor.tzinfo is None or valor.utcoffset() is None:
        raise ErroCheckpointANP(f"{campo}: timezone obrigatório")
    return valor.astimezone(timezone.utc)


def _canonical(payload: Mapping | list) -> bytes:
    try:
        return json.dumps(
            payload, sort_keys=True, ensure_ascii=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ErroCheckpointANP("checkpoint não serializável") from exc


def estado_revogacoes_local(db: sqlite3.Connection, *, ate: str) -> dict:
    """Digest determinístico de todas as revogações recebidas até o corte.

    Não consulta rede e não constitui atestação de completude do emissor.
    """
    corte = _tempo(ate, "ate")
    db.row_factory = sqlite3.Row
    rows = db.execute(
        """SELECT revogacao_id,sha,dominio,aprovacao_id,emissor_id,
                  motivo_codigo,emitido_em,recebido_em,assinatura_sha256
           FROM anp_semanal_revogacoes
           WHERE recebido_em<=? ORDER BY revogacao_id""",
        (corte.isoformat(),),
    ).fetchall()
    data = [{key: r[key] for key in _COLUNAS} for r in rows]
    return {
        "total_revogacoes": len(data),
        "hash_revogacoes": sha256(_canonical(data)).hexdigest(),
    }


def receber_checkpoint_revogacoes(
    db: sqlite3.Connection, *, checkpoint: Mapping, autoridade: Mapping,
    recebido_em_confiavel: str,
) -> dict:
    """Valida snapshot assinado, monotônico e da MESMA lista local.

    Não é um emissor de assinatura. O relógio e a autoridade são
    dependências confiáveis externas, nunca conteúdo de coleta ANP.
    """
    campos = {
        "versao", "escopo", "emissor_id", "sequencia", "cobertura_ate",
        "emitido_em", "valido_ate", "total_revogacoes", "hash_revogacoes",
        "assinatura_hmac_sha256",
    }
    if not isinstance(checkpoint, Mapping) or set(checkpoint) != campos:
        raise ErroCheckpointANP("schema de checkpoint divergente")
    if (not isinstance(autoridade, Mapping)
            or set(autoridade) != {"chave", "emissor"}
            or not isinstance(autoridade["chave"], bytes)
            or len(autoridade["chave"]) < 32
            or not isinstance(autoridade["emissor"], str)
            or not autoridade["emissor"].strip()):
        raise ErroCheckpointANP("autoridade de feed não confiável")
    if (type(checkpoint["versao"]) is not int or checkpoint["versao"] != 1
            or checkpoint["escopo"] != "ANP_LPC_REVOGACOES"
            or checkpoint["emissor_id"] != autoridade["emissor"]
            or type(checkpoint["sequencia"]) is not int
            or not 1 <= checkpoint["sequencia"] <= 2**63-1
            or type(checkpoint["total_revogacoes"]) is not int
            or not 0 <= checkpoint["total_revogacoes"] <= 100000000):
        raise ErroCheckpointANP("identidade, sequencia ou contagem inválida")
    if (not isinstance(checkpoint["hash_revogacoes"], str)
            or not _SHA.fullmatch(checkpoint["hash_revogacoes"])):
        raise ErroCheckpointANP("hash da lista de revogações inválido")
    assinatura = checkpoint["assinatura_hmac_sha256"]
    if not isinstance(assinatura, str) or not _SHA.fullmatch(assinatura):
        raise ErroCheckpointANP("assinatura do checkpoint obrigatória")
    unsigned = {k: v for k, v in checkpoint.items()
                if k != "assinatura_hmac_sha256"}
    calculada = hmac.new(
        autoridade["chave"], _PREFIX + _canonical(unsigned), sha256,
    ).hexdigest()
    if not hmac.compare_digest(assinatura, calculada):
        raise ErroCheckpointANP("assinatura do checkpoint inválida")
    emitido = _tempo(checkpoint["emitido_em"], "emitido_em")
    coberto = _tempo(checkpoint["cobertura_ate"], "cobertura_ate")
    valido = _tempo(checkpoint["valido_ate"], "valido_ate")
    recebido = _tempo(recebido_em_confiavel, "recebido_em_confiavel")
    if (not coberto <= emitido <= recebido <= valido
            or emitido - coberto > timedelta(minutes=30)
            or valido - emitido > timedelta(hours=6)
            or emitido == valido):
        raise ErroCheckpointANP("vintage, cobertura ou validade temporal incorreta")
    presente = estado_revogacoes_local(db, ate=coberto.isoformat())
    if (presente["total_revogacoes"] != checkpoint["total_revogacoes"]
            or presente["hash_revogacoes"] != checkpoint["hash_revogacoes"]):
        raise ErroCheckpointANP("checkpoint diverge da lista local; sincronização incompleta")
    fingerprint = sha256(_canonical(checkpoint)).hexdigest()
    db.row_factory = sqlite3.Row
    with db:
        anterior = db.execute(
            "SELECT * FROM anp_semanal_checkpoints WHERE sequencia=?",
            (checkpoint["sequencia"],),
        ).fetchone()
        if anterior is not None:
            if (anterior["documento_sha256"] != fingerprint
                    or anterior["recebido_em"] != recebido.isoformat()):
                raise ErroCheckpointANP("mesma sequência com conteúdo ou recepção divergentes")
            novo = False
        else:
            latest = db.execute(
                "SELECT * FROM anp_semanal_checkpoints ORDER BY sequencia DESC LIMIT 1"
            ).fetchone()
            if (latest is not None
                    and (checkpoint["sequencia"] <= latest["sequencia"]
                         or emitido.isoformat() <= latest["emitido_em"]
                         or coberto.isoformat() < latest["cobertura_ate"]
                         or recebido.isoformat() < latest["recebido_em"]
                         or checkpoint["emissor_id"] != latest["emissor_id"])):
                raise ErroCheckpointANP("rollback, replay, sequência ou emissor divergente")
            db.execute(
                """INSERT INTO anp_semanal_checkpoints
                   (sequencia,emissor_id,cobertura_ate,emitido_em,valido_ate,
                    recebido_em,total_revogacoes,hash_revogacoes,documento_sha256)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    checkpoint["sequencia"], checkpoint["emissor_id"],
                    coberto.isoformat(), emitido.isoformat(), valido.isoformat(),
                    recebido.isoformat(), presente["total_revogacoes"],
                    presente["hash_revogacoes"], fingerprint,
                ),
            )
            novo = True
    return {
        "status": "CHECKPOINT_VERIFICADO_APENAS_EM_AMBIENTE_CONTROLADO",
        "sequencia": checkpoint["sequencia"],
        "recebido_em": recebido.isoformat(),
        "cobertura_ate": coberto.isoformat(),
        "registro_novo": novo, "publicavel": False,
        "fonte_real_sincronizada": False,
    }


def verificar_frescor_revogacoes(
    db: sqlite3.Connection, *, as_of: str, tolerancia_minutos: int = 120,
) -> dict:
    """Fail-closed para leitura positiva de preço ANP.

    Apenas examina checkpoints recebidos até as_of; não usa artefatos
    futuros para declarar que o dado era seguro em data anterior.
    """
    corte = _tempo(as_of, "as_of")
    if type(tolerancia_minutos) is not int or not 1 <= tolerancia_minutos <= 360:
        raise ErroCheckpointANP("tolerância de frescor inválida")
    db.row_factory = sqlite3.Row
    ultimo = db.execute(
        """SELECT * FROM anp_semanal_checkpoints
           WHERE recebido_em<=? ORDER BY sequencia DESC LIMIT 1""",
        (corte.isoformat(),),
    ).fetchone()
    if ultimo is None:
        return {"status": "REVOGACOES_SEM_CHECKPOINT", "publicavel": False}
    cobertura = _tempo(ultimo["cobertura_ate"], "cobertura_ate")
    validade = _tempo(ultimo["valido_ate"], "valido_ate")
    if (cobertura > corte or validade < corte
            or corte - cobertura > timedelta(minutes=tolerancia_minutos)):
        return {"status": "REVOGACOES_CHECKPOINT_VENCIDO", "publicavel": False}
    dados = estado_revogacoes_local(db, ate=cobertura.isoformat())
    if (dados["total_revogacoes"] != ultimo["total_revogacoes"]
            or dados["hash_revogacoes"] != ultimo["hash_revogacoes"]):
        return {"status": "REVOGACOES_LISTA_DIVERGENTE", "publicavel": False}
    novas = db.execute(
        """SELECT 1 FROM anp_semanal_revogacoes
           WHERE recebido_em>? AND recebido_em<=? LIMIT 1""",
        (cobertura.isoformat(), corte.isoformat()),
    ).fetchone()
    if novas is not None:
        return {"status": "REVOGACOES_NAO_SINCRONIZADAS", "publicavel": False}
    return {
        "status": "CHECKPOINT_FRESCO_APENAS_LOCAL",
        "sequencia": ultimo["sequencia"], "publicavel": False,
        "cobertura_ate": cobertura.isoformat(),
    }
