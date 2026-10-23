"""Preparação editorial OFFLINE: preflight -> provas -> outbox, sem envio."""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
from datetime import datetime

from .autorizacao_envio import verificar_autorizacao
from .editorial_preflight import avaliar_previa_editorial
from .entrega_whatsapp import preparar_template
from .outbox_whatsapp import (
    _fingerprint, _revisar_preparado, _esquema,
    registrar_edicao, registrar_autorizacao, consultar_envio,
)
from .provas_externas_envio import verificar_pacote_externo
from .registry_emissores import emissores_confiaveis


CAMPOS = frozenset({
    "edicao", "gerado_em", "noticias", "cotacoes", "fretes",
    "destinatario", "nome_template", "resumo_template", "url_briefing",
    "documento", "assinatura", "comprovantes",
})


class ErroPacoteOffline(ValueError):
    pass


def avaliar_pacote_offline(pacote: dict) -> dict:
    """Recalcula o preflight; nenhuma escrita ou autorização de distribuição."""
    if not isinstance(pacote, dict) or set(pacote) != CAMPOS:
        raise ErroPacoteOffline("contrato editorial incompleto ou inesperado")
    edicao = pacote["edicao"]
    if not isinstance(edicao, dict):
        raise ErroPacoteOffline("edição não estruturada")
    gerado_em = pacote["gerado_em"]
    if gerado_em != edicao.get("gerado_em"):
        raise ErroPacoteOffline("horário de geração divergente")
    prova = avaliar_previa_editorial(
        edicao=edicao, gerado_em=gerado_em, noticias=pacote["noticias"],
        cotacoes=pacote["cotacoes"], fretes=pacote["fretes"],
    )
    return {"estado": "PREVALIDADO_OFFLINE" if prova["apto_revisao"]
            else "BLOQUEADO_PREFLIGHT",
            "preflight": prova, "envio_habilitado": False,
            "nota": "Pré-validação não prova licença nem autoriza disparo"}


def registrar_pacote_offline(
    con: sqlite3.Connection, pacote: dict, *,
    chave_destinatario: bytes, chave_auditoria: bytes, emissores: dict
) -> dict:
    """Valida provas e registry ANTES de registrar edição. Nunca despacha."""
    revisao = avaliar_pacote_offline(pacote)
    if revisao["estado"] != "PREVALIDADO_OFFLINE":
        return {"estado": "BLOQUEADO_PREFLIGHT",
                "bloqueios": revisao["preflight"]["bloqueios"],
                "envio_habilitado": False, "mutacao": False}

    edicao = pacote["edicao"]
    # Flags provisórias apenas para compor o payload candidato offline.
    # A autenticidade externa do consentimento/template é exigida abaixo.
    modelo = preparar_template(
        destino=pacote["destinatario"], template=pacote["nome_template"],
        resumo=pacote["resumo_template"], link=pacote["url_briefing"],
        gerado_em=pacote["gerado_em"],
        opt_in_registrado=True, template_aprovado=True,
    )
    destino, _, chave = _revisar_preparado(modelo)
    documento = pacote["documento"]
    if not isinstance(documento, dict):
        raise ErroPacoteOffline("autorização não estruturada")
    instante = datetime.fromisoformat(pacote["gerado_em"].replace("Z", "+00:00"))
    dia = instante.date().isoformat()
    if (documento.get("idempotency_key") != chave
            or documento.get("edicao") != dia
            or documento.get("sha256_editorial") != edicao.get("sha256")
            or documento.get("payload_sha256") != _fingerprint(modelo["payload"])
            or documento.get("destinatario_hmac") != hmac.new(
                chave_destinatario, destino.encode(), hashlib.sha256
            ).hexdigest()):
        raise PermissionError("autorização não vinculada ao preparado")
    sig = pacote["assinatura"]
    verificar_autorizacao(documento, sig, chave_auditoria=chave_auditoria)
    verificar_pacote_externo(documento, pacote["comprovantes"], emissores,
                            chave_auditoria=chave_auditoria)
    _esquema(con)
    con.execute("BEGIN IMMEDIATE")
    try:
        emissores_confiaveis(con, emissores)
        con.commit()
    except Exception:
        con.rollback()
        raise

    # A outbox revalida registry, opt-out e provas na própria transação.
    registro = registrar_edicao(
        con, modelo, edicao=dia, chave_destinatario=chave_destinatario)
    comprovada = dict(edicao, preflight_editorial=revisao["preflight"])
    aprovado = registrar_autorizacao(
        con, modelo, edicao_editorial=comprovada,
        documento=documento, assinatura=sig, chave_auditoria=chave_auditoria,
        comprovantes=pacote["comprovantes"], emissores=emissores,
    )
    return {
        "estado": "EDICAO_REGISTRADA_OFFLINE_SEM_ENVIO",
        "id_edicao_resumido": chave[:12],
        "ja_existia": registro["ja_existia"],
        "autorizacao": aprovado["estado"],
        "estado_outbox": consultar_envio(con, chave)["estado"],
        "pendencias_editoriais": revisao["preflight"]["lacunas"],
        "envio_habilitado": False, "mutacao": True,
    }
