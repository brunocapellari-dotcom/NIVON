"""Normalizador OFFLINE da Selic diária SGS 11 (BCB) com data informada.

Não converte taxa diária em meta Selic anual, CDI ou IPCA. Fonte primária:
https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json
Sem requisição HTTP, armazenamento, deploy ou agendamento.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, date, timezone
from decimal import Decimal, InvalidOperation

SERIE_SGS = 11
URL_DOC = "https://dadosabertos.bcb.gov.br/"
URL_PONTUAL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json"


class ErroSGS(ValueError):
    pass


def _sem_duplicata(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ErroSGS("JSON com chave duplicada")
        result[k] = v
    return result


def _coleta(valor):
    if not isinstance(valor, str):
        raise ErroSGS("carimbo de coleta ausente")
    try:
        d = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroSGS("data de coleta ISO inválida") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroSGS("coleta exige fuso horário")
    return d.astimezone(timezone.utc).isoformat()


def normalizar_selic_diaria(payload: bytes, *, coletado_em: str) -> dict:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 250_000:
        raise ErroSGS("payload ausente ou acima de 250 kB")
    coleta = _coleta(coletado_em)
    try:
        obj = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_sem_duplicata)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroSGS("JSON SGS inválido") from exc
    if not isinstance(obj, list) or not 1 <= len(obj) <= 1500:
        raise ErroSGS("SGS exige lista limitada não vazia")
    obs, dates = [], set()
    for row in obj:
        if not isinstance(row, dict):
            raise ErroSGS("observação SGS não é objeto")
        dia = row.get("data")
        valor = row.get("valor")
        if not isinstance(dia, str) or not re.fullmatch(r"\d\d/\d\d/\d{4}", dia):
            raise ErroSGS("data de referência DD/MM/AAAA ausente")
        try:
            dt = datetime.strptime(dia, "%d/%m/%Y").date()
        except ValueError as exc:
            raise ErroSGS("data de referência inválida") from exc
        if dt.isoformat() in dates:
            raise ErroSGS("data duplicada")
        dates.add(dt.isoformat())
        if (not isinstance(valor, str) or
                not re.fullmatch(r"-?\d+(?:[.,]\d{1,12})?", valor)):
            raise ErroSGS("taxa diária não é decimal no esquema oficial")
        try:
            v = Decimal(valor.replace(",", "."))
        except InvalidOperation as exc:
            raise ErroSGS("taxa diária inválida") from exc
        if not v.is_finite() or not 0 <= v <= 10:
            raise ErroSGS("Selic diária fora dos limites")
        obs.append({
            "data_referencia": dt.isoformat(),
            "competencia": dt.strftime("%Y-%m"),
            "publicacao": None,
            "coleta": coleta,
            "valor_pct_ao_dia": format(v, "f"),
            "unidade": "PERCENTUAL_AO_DIA",
            "serie_sgs": SERIE_SGS,
            "natureza": "TAXA_SELIC_DIARIA_OBSERVADA_SGS_NAO_META_ANUAL",
        })
    obs.sort(key=lambda x: x["data_referencia"])
    return {
        "dataset_id": "BCB_SGS_TAXA_SELIC_DIARIA",
        "fonte_id": "BCB",
        "serie": SERIE_SGS,
        "observacoes": obs,
        "coleta": coleta,
        "sha256_original": hashlib.sha256(payload).hexdigest(),
        "documentacao": URL_DOC,
        "sem_hora_publicacao": True,
        "apto_publicacao_automatica": False,
        "status": "NORMALIZADO_OFFLINE_NAO_HOMOLOGADO",
    }
