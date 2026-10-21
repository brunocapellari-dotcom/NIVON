"""Adaptador CFTC COT Disaggregated Futures Only, via Socrata oficial.

Consulta pontual por data exata e produto nomeado (sem busca irrestrita).
Dados de POSICIONAMENTO de terça, NÃO preços CME/CBOT. O horário real de
publicação não é inferido da data de referência.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

BASE = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
MERCADOS = frozenset({"SOYBEANS", "CORN", "WHEAT", "SOYBEAN OIL", "SOYBEAN MEAL", "COTTON"})
CAMPOS_POSICOES = (
    "open_interest_all",
    "prod_merc_positions_long_all",
    "prod_merc_positions_short_all",
    "swap_positions_long_all",
    "swap__positions_short_all",
    "m_money_positions_long_all",
    "m_money_positions_short_all",
    "m_money_positions_spread_all",
)


class ErroCFTC(ValueError):
    pass


def planejar_cot(*, data: str, mercado: str, limite: int = 100) -> str:
    try:
        dia = date.fromisoformat(data)
    except (TypeError, ValueError) as exc:
        raise ErroCFTC("data AAAA-MM-DD inválida") from exc
    if data != dia.isoformat() or mercado not in MERCADOS:
        raise ErroCFTC("data/mercado não permitido")
    if type(limite) is not int or not 1 <= limite <= 500:
        raise ErroCFTC("limite máximo 500 por consulta")
    # Sem entrada SQL arbitrária; only allowlisted nominal markets.
    where = (f"report_date_as_yyyy_mm_dd = '{data}T00:00:00.000' "
             f"AND upper(market_and_exchange_names) like '%{mercado}%'")
    params = {"$where": where, "$order": "market_and_exchange_names ASC",
              "$limit": str(limite)}
    return BASE + "?" + urlencode(params)


def _unique_pairs(pairs):
    o = {}
    for k, v in pairs:
        if k in o:
            raise ErroCFTC("chave JSON duplicada")
        o[k] = v
    return o


def _instante(s):
    if not isinstance(s, str):
        raise ErroCFTC("coleta exige data/hora ISO")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroCFTC("coleta inválida") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroCFTC("coleta sem timezone")
    return d.astimezone(timezone.utc).isoformat()


def _posicao(n, campo):
    if n is None:
        return None
    if type(n) is bool or not isinstance(n, (str, int, float)):
        raise ErroCFTC("posição inválida: " + campo)
    try:
        x = Decimal(str(n))
    except InvalidOperation as exc:
        raise ErroCFTC("posição não numérica") from exc
    if not x.is_finite() or x < 0 or x != x.to_integral_value():
        raise ErroCFTC("contratos devem ser números inteiros não negativos")
    return int(x)


def normalizar_cot(payload: bytes, *, data: str, mercado: str,
                  limite: int, coletado_em: str) -> dict:
    url = planejar_cot(data=data, mercado=mercado, limite=limite)
    coleta = _instante(coletado_em)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 1_000_000:
        raise ErroCFTC("payload vazio ou maior que 1MB")
    try:
        doc = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroCFTC("resposta JSON inválida") from exc
    if not isinstance(doc, list) or len(doc) > limite:
        raise ErroCFTC("lista retornada excede o limite")
    if len(doc) == limite:
        raise ErroCFTC("possível paginação/truncamento; reduza o recorte")
    res, vistas = [], set()
    for row in doc:
        if not isinstance(row, dict):
            raise ErroCFTC("observação não é objeto")
        nome = row.get("market_and_exchange_names")
        dt = row.get("report_date_as_yyyy_mm_dd")
        if not isinstance(nome, str) or mercado not in nome.upper() or not isinstance(dt, str):
            raise ErroCFTC("mercado/dia ausente ou diferente do filtro")
        try:
            day = date.fromisoformat(dt[:10])
        except ValueError as exc:
            raise ErroCFTC("data de posição inválida") from exc
        if dt[:10] != data or not re.fullmatch(r"\d{4}-\d\d-\d\d(?:T00:00:00(?:\.\d{1,3})?)?", dt):
            raise ErroCFTC("posição fora da data de referência")
        codigo = row.get("cftc_contract_market_code")
        if not isinstance(codigo, str) or not 1 <= len(codigo) <= 25:
            raise ErroCFTC("código de contrato ausente")
        identidade = (codigo, dt, nome)
        if identidade in vistas:
            raise ErroCFTC("registro de contrato repetido")
        vistas.add(identidade)
        posicoes = {k: _posicao(row.get(k), k) for k in CAMPOS_POSICOES}
        if posicoes["open_interest_all"] is None:
            raise ErroCFTC("open interest ausente")
        res.append({
            "contrato": codigo, "mercado_contrato": nome.strip(),
            "data_referencia": day.isoformat(), "competencia": day.strftime("%Y-%m"),
            "coleta": coleta, "publicacao": None,
            "natureza": "POSICOES_FUTUROS_CFTC_NAO_PRECOS_NEM_SPOT",
            "posicoes_contratos": posicoes,
        })
    return {"dataset_id": "CFTC_COT_WEEKLY", "fonte_id": "CFTC",
            "consulta_url": url, "coleta": coleta, "observacoes": res,
            "total_retorno": len(res),
            "sha256_original": hashlib.sha256(payload).hexdigest(),
            "relatorio": "DISAGGREGATED_FUTURES_ONLY",
            "apto_publicacao": False, "estado": "COLETA_PONTUAL_NAO_HOMOLOGADA"}
