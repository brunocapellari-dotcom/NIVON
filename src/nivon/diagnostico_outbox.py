"""Diagnóstico offline, somente leitura, da outbox e confiança de emissores.

Nenhuma função envia, reserva, apaga ou reativa autorização. Resultado
redigido sem números telefônicos, tokens, texto ou provas brutas.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .registry_emissores import resumo_registry


def _tabela(con: sqlite3.Connection, nome: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)
    ).fetchone())


def diagnosticar_outbox(con: sqlite3.Connection, *, agora: datetime | None = None) -> dict:
    """Avalia segurança/estado local, NÃO autoriza envio pelo resultado.

    Considera o estado SQLite persistido, não a qualidade externa dos fatos.
    Desconhecer qualquer contrato resulta em bloqueio diagnóstico.
    """
    if con.in_transaction:
        raise ValueError("diagnóstico requer snapshot sem transação pendente")
    now = agora if agora is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("relógio do diagnóstico sem fuso")
    now = now.astimezone(timezone.utc)
    obrigatorias = {
        "nivon_envios", "nivon_autorizacoes", "nivon_provas_externas",
        "nivon_optouts_destinatario", "nivon_registry_root",
        "nivon_registry_emissores",
    }
    presentes = {name for name in obrigatorias if _tabela(con, name)}
    if presentes != obrigatorias:
        return {
            "estado": "NAO_PROVISIONADA", "emissores": {
                "provisionado": False, "total": 0, "ativos": 0,
                "revogados": 0, "apto_registry": False,
            },
            "edicoes": [], "total": 0,
            "pendencias": sorted(obrigatorias - presentes),
            "envio_habilitado": False,
        }
    registry = resumo_registry(con)
    rows = con.execute("""SELECT e.idempotency_key,e.edicao,e.estado,e.tentativas,
        e.provider_message_id, a.documento_sha256,a.valido_ate,a.revogado_em,
        p.comprovantes_sha256, o.destinatario_hmac
        FROM nivon_envios e
        LEFT JOIN nivon_autorizacoes a ON a.idempotency_key=e.idempotency_key
        LEFT JOIN nivon_provas_externas p ON p.idempotency_key=e.idempotency_key
        LEFT JOIN nivon_optouts_destinatario o ON
           o.destinatario_hmac=e.destinatario_hmac
        ORDER BY e.edicao,e.idempotency_key""").fetchall()
    itens = []
    for key, edicao, estado, tentativas, provider, documento, validade, revogacao, provas, optout in rows:
        motivos = []
        if not registry["apto_registry"]:
            motivos.append("EMISSOR_AUSENTE_OU_REVOGADO")
        if optout is not None:
            motivos.append("OPT_OUT_DESTINATARIO")
        if revogacao:
            motivos.append("REVOGACAO_EDICAO")
        if not documento or not provas:
            motivos.append("EVIDENCIAS_EXTERNAS_AUSENTES")
        if validade:
            try:
                instante = datetime.fromisoformat(validade.replace("Z","+00:00"))
                if instante.tzinfo is None or instante.astimezone(timezone.utc) <= now:
                    motivos.append("APROVACAO_EXPIRADA")
            except (ValueError,TypeError):
                motivos.append("APROVACAO_DATA_INVALIDA")
        elif estado == "PREPARADO":
            motivos.append("APROVACAO_AUSENTE")
        if estado == "ENVIO_INDETERMINADO":
            motivos.append("RECONCILIAR_PROVEDOR_SEM_RETRY")
        if estado != "PREPARADO":
            motivos.append("TENTATIVA_JA_RESERVADA_OU_FINALIZADA")
        if tentativas is None or tentativas > 1 or tentativas < 0:
            motivos.append("TENTATIVAS_INVALIDAS")
        if estado == "PREPARADO" and tentativas != 0:
            motivos.append("PREPARADO_COM_TENTATIVA")
        motivos = sorted(set(motivos))
        itens.append({
            "id_edicao_resumido": key[:12], "data": edicao,
            "estado_outbox": estado, "tentativas": tentativas,
            "ack_identificado": bool(provider), "bloqueios": motivos,
            "diagnostico": (
                "EVIDENCIAS_ESTRUTURAIS_COMPLETAS_OFFLINE"
                if estado == "PREPARADO" and not motivos
                else "BLOQUEADO_OU_PENDENTE"
            ),
        })
    return {
        "estado": "DIAGNOSTICO_OFFLINE", "emissores": registry,
        "total": len(itens), "edicoes": itens,
        "pendencias": sorted({motivo for item in itens for motivo in item["bloqueios"]}),
        "envio_habilitado": False,
        "aviso": "Snapshot de banco local; não confirma consentimento, direitos ou revisão independentes",
    }
