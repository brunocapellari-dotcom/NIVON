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
        noticias_editoriais=pacote["noticias"],
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


def avaliar_lote_offline(pacotes: list[dict]) -> dict:
    """Valida vários pacotes sem abrir banco, usar chaves ou enviar."""
    if not isinstance(pacotes, list) or not 1 <= len(pacotes) <= 200:
        raise ErroPacoteOffline("lote deve conter de 1 a 200 pacotes")
    resultados = []
    for indice, pacote in enumerate(pacotes):
        try:
            resultado = avaliar_pacote_offline(pacote)
            estado = resultado["estado"]
            bloqueios = resultado["preflight"]["bloqueios"][:20]
        except (ValueError, TypeError, KeyError):
            estado, bloqueios = "PACOTE_INVALIDO", ["CONTRATO_INCOMPLETO"]
        resultados.append({"indice": indice, "estado": estado,
                           "bloqueios": bloqueios})
    return {
        "estado": "LOTE_VALIDADO_OFFLINE",
        "total": len(resultados),
        "prevalidados": sum(x["estado"] == "PREVALIDADO_OFFLINE" for x in resultados),
        "bloqueados": sum(x["estado"] != "PREVALIDADO_OFFLINE" for x in resultados),
        "resultados": resultados, "envio_habilitado": False,
    }


def registrar_lote_offline(
    con: sqlite3.Connection, pacotes: list[dict], *,
    chave_destinatario: bytes, chave_auditoria: bytes, emissores: dict
) -> dict:
    """Registra um lote de edições válidas, isolando bloqueios por pacote.

    Cada edição faz sua própria verificação e transações SQLite. Uma falha
    de dados ou assinatura reprova só aquele pacote; falha do banco sobe
    para o operador (nunca fingir sucesso). Não há callback ou POST.
    """
    if not isinstance(pacotes, list) or not 1 <= len(pacotes) <= 200:
        raise ErroPacoteOffline("lote deve conter de 1 a 200 pacotes")
    vistos = set()
    resultados = []
    for indice, pacote in enumerate(pacotes):
        chave = None
        if isinstance(pacote, dict) and isinstance(pacote.get("documento"), dict):
            chave = pacote["documento"].get("idempotency_key")
        if isinstance(chave, str) and chave in vistos:
            resultados.append({"indice": indice, "estado": "REPETIDO_NO_LOTE"})
            continue
        # Só a edição REGISTRADA conta como vista. Caso contrário,
        # um pacote inválido impediria um válido posterior com o mesmo ID.
        try:
            result = registrar_pacote_offline(
                con, pacote, chave_destinatario=chave_destinatario,
                chave_auditoria=chave_auditoria, emissores=emissores)
            estado = result["estado"]
            if estado == "EDICAO_REGISTRADA_OFFLINE_SEM_ENVIO" and isinstance(chave, str):
                vistos.add(chave)
        except (PermissionError, ValueError, TypeError, KeyError):
            estado = "REPROVADO_POR_PROVA_OU_CONTRATO"
        resultados.append({"indice": indice, "estado": estado})
    aprovados = sum(x["estado"] == "EDICAO_REGISTRADA_OFFLINE_SEM_ENVIO"
                    for x in resultados)
    return {
        "estado": "LOTE_REGISTRADO_OFFLINE_SEM_ENVIO", "total": len(resultados),
        "registrados": aprovados, "bloqueados": len(resultados) - aprovados,
        "resultados": resultados, "envio_habilitado": False,
    }
