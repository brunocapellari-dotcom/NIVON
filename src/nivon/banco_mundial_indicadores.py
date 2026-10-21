"""Parser de indicadores anuais oficiais do Banco Mundial API v2, sem HTTP.

Indicadores restritos a unidades conhecidas; atualização da fonte NÃO é
equivalente ao carimbo de publicação individual da série.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal

from urllib.parse import urlencode


INDICADORES = {
    "SP.POP.TOTL": ("PESSOAS", "populacao_total"),
    "NY.GDP.MKTP.CD": ("USD_CORRENTES", "pib_usd_correntes"),
    "NV.AGR.TOTL.ZS": ("PERCENTUAL_PIB", "agricultura_valor_adicionado_pct_pib"),
}
BASE = "https://api.worldbank.org/v2/country/BR/indicator/"


class ErroBancoMundial(ValueError):
    pass


def planejar_indicador(*, indicador: str, inicio: int, fim: int) -> str:
    if indicador not in INDICADORES or type(inicio) is not int or type(fim) is not int:
        raise ErroBancoMundial("indicador/anos não permitidos")
    if not 1960 <= inicio <= fim <= 2100 or fim - inicio > 80:
        raise ErroBancoMundial("intervalo fora da janela controlada")
    return (BASE + indicador + "?" +
            urlencode({"format": "json", "date": f"{inicio}:{fim}",
                       "per_page": "100", "page": "1"}))


def _unicos(pares):
    d = {}
    for k, v in pares:
        if k in d:
            raise ErroBancoMundial("chave JSON duplicada")
        d[k] = v
    return d


def _coleta(valor: str) -> str:
    if not isinstance(valor, str):
        raise ErroBancoMundial("coleta ausente")
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroBancoMundial("coleta inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroBancoMundial("coleta sem timezone")
    return dt.astimezone(timezone.utc).isoformat()


def _inteiro(value, campo):
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    raise ErroBancoMundial(campo + " inválido")


def normalizar_indicador(payload: bytes, *, indicador: str, inicio: int,
                        fim: int, coletado_em: str) -> dict:
    url = planejar_indicador(indicador=indicador, inicio=inicio, fim=fim)
    coleta = _coleta(coletado_em)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 500_000:
        raise ErroBancoMundial("payload inválido ou maior que 500 kB")
    try:
        doc = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unicos)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroBancoMundial("JSON inválido") from exc
    if not isinstance(doc, list) or len(doc) != 2 or not isinstance(doc[0], dict) or not isinstance(doc[1], list):
        raise ErroBancoMundial("API deve retornar [metadados, observações]")
    meta, itens = doc
    page, pages, total = (_inteiro(meta.get(k), k) for k in ("page", "pages", "total"))
    per_page = _inteiro(meta.get("per_page"), "per_page")
    if page != 1 or pages != 1 or total > per_page or total != len(itens) or len(itens) > 100:
        raise ErroBancoMundial("paginação incompleta ou contagem incompatível")
    atualizado = meta.get("lastupdated")
    if atualizado is not None:
        if not isinstance(atualizado, str):
            raise ErroBancoMundial("lastupdated inválido")
        try:
            atualizado = date.fromisoformat(atualizado).isoformat()
        except ValueError as exc:
            raise ErroBancoMundial("lastupdated inválido") from exc
    unidade, metrica = INDICADORES[indicador]
    saida, anos = [], set()
    for item in itens:
        if not isinstance(item, dict):
            raise ErroBancoMundial("observação não é objeto")
        obj_indicador = item.get("indicator")
        obj_pais = item.get("country")
        if (not isinstance(obj_indicador, dict) or obj_indicador.get("id") != indicador
                or not isinstance(obj_pais, dict) or obj_pais.get("id") != "BR"
                or item.get("countryiso3code") != "BRA"):
            raise ErroBancoMundial("país ou indicador divergente")
        ano = item.get("date")
        if (not isinstance(ano, str) or not re.fullmatch(r"[0-9]{4}", ano)
                or not inicio <= int(ano) <= fim or ano in anos):
            raise ErroBancoMundial("ano inválido, repetido ou fora do plano")
        anos.add(ano)
        valor = item.get("value")
        if valor is not None:
            if type(valor) not in (int, float):
                raise ErroBancoMundial("valor numérico inválido")
            numero = Decimal(str(valor))
            if not numero.is_finite() or numero < 0:
                raise ErroBancoMundial("valor negativo/não finito")
            if indicador == "NV.AGR.TOTL.ZS" and numero > 100:
                raise ErroBancoMundial("percentual maior que 100")
            valor = format(numero, "f")
        saida.append({
            "pais": "BRA", "indicador": indicador, "metrica": metrica,
            "ano_referencia": ano, "competencia": ano,
            "valor": valor, "unidade": unidade,
            "observacao_status": item.get("obs_status") or None,
            "publicacao": None, "coleta": coleta,
            "natureza": "ESTATISTICA_OFICIAL_BANCO_MUNDIAL_NAO_COTACAO_MERCADO",
        })
    saida.sort(key=lambda x: x["ano_referencia"])
    return {"dataset_id": "WB_INDICADORES_MACRO_BR", "fonte_id": "WB",
            "consulta_url": url, "indicador": indicador,
            "ultima_atualizacao_fonte": atualizado,
            "publicacao_individual": None, "coleta": coleta,
            "numero_observacoes": len(saida), "observacoes": saida,
            "sha256_original": hashlib.sha256(payload).hexdigest(),
            "estado": "NORMALIZADO_PONTUAL_NAO_HOMOLOGADO",
            "apto_publicacao_automatica": False}
