"""BCB Focus: expectativas de mercado anuais (projetadas), OData pública.

Não confundir taxa Selic observada/SGS com expectativa Selic. Data da pesquisa
não é automaticamente data de divulgação pública. Nenhuma previsão pode
entrar em backtest 'as-of' sem vintage de publicação confirmado.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

BASE = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais"
INDICADORES = {
    "Câmbio": "BRL_POR_USD_ESPERADO",
    "Selic": "PERCENTUAL_ANUAL_ESPERADO",
    "IPCA": "PERCENTUAL_ANUAL_ESPERADO",
    "PIB Total": "VAR_PCT_ANUAL_ESPERADA",
}


class ErroFocus(ValueError):
    pass


def planejar_focus(*, indicador: str, inicio: str, fim: str, max_itens: int = 200) -> str:
    if indicador not in INDICADORES or type(max_itens) is not int or not 1 <= max_itens <= 500:
        raise ErroFocus("indicador não homologado/limite inválido")
    try:
        a, b = date.fromisoformat(inicio), date.fromisoformat(fim)
    except (TypeError, ValueError) as exc:
        raise ErroFocus("datas inválidas") from exc
    if (a.isoformat() != inicio or b.isoformat() != fim or a > b
            or (b - a).days > 30):
        raise ErroFocus("intervalo máximo 31 dias")
    filtro = (f"Indicador eq '{indicador}' and Data ge '{inicio}' "
              f"and Data le '{fim}'")
    qs = {"$filter": filtro,
          "$select": "Indicador,Data,DataReferencia,Media,Mediana",
          "$orderby": "Data desc", "$top": max_itens, "$format": "json"}
    return BASE + "?" + urlencode(qs)


def _unico(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ErroFocus("JSON com chave repetida")
        out[k] = v
    return out


def _coleta(iso):
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ErroFocus("data coleta inválida") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ErroFocus("coleta exige timezone")
    return t.astimezone(timezone.utc).isoformat()


def _decimal(valor, label):
    if valor is None or isinstance(valor, bool) or not isinstance(valor, (float, int, str)):
        raise ErroFocus("ausência ou erro decimal: " + label)
    try:
        v = Decimal(str(valor))
    except InvalidOperation as exc:
        raise ErroFocus("valor não numérico") from exc
    if not v.is_finite() or abs(v) > 100_000:
        raise ErroFocus("valor não finito/fora de amplitude sanitária")
    return format(v, "f")


def normalizar_focus(payload: bytes, *, indicador: str, inicio: str, fim: str,
                    max_itens: int, coletado_em: str) -> dict:
    url = planejar_focus(indicador=indicador, inicio=inicio, fim=fim,
                        max_itens=max_itens)
    coleta = _coleta(coletado_em)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 1_000_000:
        raise ErroFocus("payload ausente ou demasiado")
    try:
        obj = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unico)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroFocus("JSON OData inválido") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("value"), list):
        raise ErroFocus("OData exige objeto com value[]")
    if "@odata.nextLink" in obj or "odata.nextLink" in obj or len(obj["value"]) >= max_itens:
        raise ErroFocus("truncamento/paginação; dividir intervalo")
    linhas, keys = [], set()
    for row in obj["value"]:
        if not isinstance(row, dict) or row.get("Indicador") != indicador:
            raise ErroFocus("indicador divergente")
        d = row.get("Data")
        ref = row.get("DataReferencia")
        try:
            dt = date.fromisoformat(d)
        except (ValueError, TypeError) as exc:
            raise ErroFocus("Data pesquisada inválida") from exc
        if not inicio <= dt.isoformat() <= fim:
            raise ErroFocus("data fora do filtro")
        if type(ref) is int:
            ref = str(ref)
        if not isinstance(ref, str) or not re.fullmatch(r"20\d{2}|21\d{2}", ref):
            raise ErroFocus("ano de referência inválido")
        key = (indicador, dt.isoformat(), ref)
        if key in keys:
            raise ErroFocus("observação duplicada")
        keys.add(key)
        media = _decimal(row.get("Media"), "Media")
        mediana = _decimal(row.get("Mediana"), "Mediana")
        linhas.append({
            "indicador": indicador, "data_pesquisa": dt.isoformat(),
            "ano_alvo": ref, "media": media, "mediana": mediana,
            "unidade": INDICADORES[indicador], "data_referencia": ref,
            "competencia": dt.strftime("%Y-%m"), "publicacao": None,
            "coleta": coleta, "natureza": "PROJECAO_CONSENSO_MERCADO_NAO_PREVISAO_DO_BCB",
        })
    return {"dataset_id": "BCB_SGS_FOCUS", "fonte_id": "BCB",
            "consulta_url": url, "observacoes": linhas, "quantidade": len(linhas),
            "sha256_original": hashlib.sha256(payload).hexdigest(),
            "coleta": coleta, "publicacao_comprovada": False,
            "apto_backtest_asof": False, "apto_publicacao_automatica": False,
            "estado": "FOCUS_NORMALIZADO_NAO_HOMOLOGADO"}
