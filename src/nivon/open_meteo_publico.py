"""Consulta pontual PLANEJADA e parser OFFLINE Open-Meteo para uso não comercial.

Fonte modelada, não estação observacional. Sem chamadas HTTP ou agendamento;
não confundir previsão corrente com análise histórica ERA5. Exige proveniência
temporal e licenciamento CC BY 4.0, sujeito aos termos do serviço gratuito.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from urllib.parse import urlencode

FORECAST_API = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
VARIAVEIS = ("precipitation_sum", "temperature_2m_max", "temperature_2m_min")
LIMITES = {"precipitation_sum": (0, 1500),
           "temperature_2m_max": (-90, 65),
           "temperature_2m_min": (-100, 60)}
UNIDADES = {"precipitation_sum": "mm",
            "temperature_2m_max": "°C",
            "temperature_2m_min": "°C"}
SERIES = {"previsao": "OPEN_METEO_PREVISAO_DIARIA",
          "reanalise": "OPEN_METEO_HISTORICO_REANALISE"}


class ErroOpenMeteo(ValueError):
    pass


def _coleta(valor: str) -> str:
    if not isinstance(valor, str):
        raise ErroOpenMeteo("data de coleta obrigatória")
    try:
        instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroOpenMeteo("data de coleta inválida") from exc
    if instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroOpenMeteo("coleta sem timezone")
    return instante.astimezone(timezone.utc).isoformat()


def _coordenada(valor, limite: int) -> str:
    if type(valor) not in (float, int) or not math.isfinite(valor) or not -limite <= valor <= limite:
        raise ErroOpenMeteo("coordenada fora do domínio")
    return str(float(valor))


def planejar_consulta(*, latitude: float, longitude: float, tipo: str,
                      inicio: str | None = None, fim: str | None = None,
                      dias_previsao: int = 7) -> str:
    """URL pontual permitida pelos termos da API; não iniciar varredura de grade."""
    lat, lon = _coordenada(latitude, 90), _coordenada(longitude, 180)
    if tipo not in SERIES:
        raise ErroOpenMeteo("tipo deve ser previsao ou reanalise")
    params = {"latitude": lat, "longitude": lon,
              "daily": ",".join(VARIAVEIS), "timezone": "UTC"}
    if tipo == "previsao":
        if inicio is not None or fim is not None or type(dias_previsao) is not int or not 1 <= dias_previsao <= 16:
            raise ErroOpenMeteo("previsão de 1 a 16 dias, sem datas de reanálise")
        params["forecast_days"] = dias_previsao
        base = FORECAST_API
    else:
        if inicio is None or fim is None:
            raise ErroOpenMeteo("intervalo explícito obrigatório no arquivo histórico")
        try:
            a, b = date.fromisoformat(inicio), date.fromisoformat(fim)
        except (TypeError, ValueError) as exc:
            raise ErroOpenMeteo("datas históricas inválidas") from exc
        if (inicio != a.isoformat() or fim != b.isoformat() or
                a > b or (b - a).days > 366):
            raise ErroOpenMeteo("janela histórica superior a 367 dias/invertida")
        params.update(start_date=inicio, end_date=fim)
        base = ARCHIVE_API
    return base + "?" + urlencode(params)


def _sem_chave_repetida(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ErroOpenMeteo("JSON com chave repetida")
        out[k] = v
    return out


def normalizar_diario(payload: bytes, *, tipo: str, coletado_em: str,
                      latitude_solicitada: float, longitude_solicitada: float) -> dict:
    """Normaliza registro de uma consulta; data de previsão não é publicação.

    daily.time precisa ser data ISO única crescente em UTC. Se tempo de emissão
    não foi fornecido, publicação fica None e comparações point-in-time bloqueadas.
    """
    if tipo not in SERIES:
        raise ErroOpenMeteo("tipo de série inválido")
    esperado_lat = float(_coordenada(latitude_solicitada, 90))
    esperado_lon = float(_coordenada(longitude_solicitada, 180))
    coleta = _coleta(coletado_em)
    if not isinstance(payload, bytes) or not (1 <= len(payload) <= 2_000_000):
        raise ErroOpenMeteo("JSON ausente ou superior a 2 MB")
    try:
        doc = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_sem_chave_repetida)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroOpenMeteo("JSON inválido") from exc
    if not isinstance(doc, dict) or doc.get("error") is True:
        raise ErroOpenMeteo("API retornou erro ou objeto inválido")
    if doc.get("timezone") != "GMT" and doc.get("timezone") != "UTC":
        raise ErroOpenMeteo("resposta fora do timezone UTC contratado")
    if type(doc.get("utc_offset_seconds")) is not int or doc["utc_offset_seconds"] != 0:
        raise ErroOpenMeteo("UTC offset divergente")
    for chave, esperado in (("latitude", esperado_lat), ("longitude", esperado_lon)):
        valor = doc.get(chave)
        if type(valor) not in (int, float) or not math.isfinite(valor) or abs(valor - esperado) > 1.0:
            raise ErroOpenMeteo("posição da grade divergente da consulta")
    daily = doc.get("daily")
    units = doc.get("daily_units")
    if not isinstance(daily, dict) or not isinstance(units, dict):
        raise ErroOpenMeteo("daily/daily_units ausentes")
    tempo = daily.get("time")
    if (not isinstance(tempo, list) or not 1 <= len(tempo) <= 367
            or units.get("time") != "iso8601"):
        raise ErroOpenMeteo("datas diárias ou unidade temporal inválidas")
    for var in VARIAVEIS:
        if not isinstance(daily.get(var), list) or len(daily[var]) != len(tempo):
            raise ErroOpenMeteo("variável diária ausente ou comprimento inconsistente: " + var)
        if units.get(var) != UNIDADES[var]:
            raise ErroOpenMeteo("unidade de medida inesperada: " + var)
    linhas, antes = [], None
    for i, data in enumerate(tempo):
        if not isinstance(data, str):
            raise ErroOpenMeteo("data diária inválida")
        try:
            dt = date.fromisoformat(data)
        except ValueError as exc:
            raise ErroOpenMeteo("data diária inválida") from exc
        if data != dt.isoformat() or (antes is not None and dt <= antes):
            raise ErroOpenMeteo("datas duplicadas, fora de ordem ou não canônicas")
        antes = dt
        linha = {}
        for var in VARIAVEIS:
            valor = daily[var][i]
            if valor is None:
                linha[var] = None
                continue
            lo, hi = LIMITES[var]
            if type(valor) not in (int, float) or not math.isfinite(valor) or not lo <= valor <= hi:
                raise ErroOpenMeteo("valor meteorológico inválido: " + var)
            linha[var] = float(valor)
        if (linha["temperature_2m_min"] is not None and
                linha["temperature_2m_max"] is not None and
                linha["temperature_2m_min"] > linha["temperature_2m_max"]):
            raise ErroOpenMeteo("temperatura mínima maior que máxima")
        if all(linha[v] is None for v in VARIAVEIS):
            raise ErroOpenMeteo("dia sem dados não representa chuva zero")
        linhas.append({
            "data_referencia": data,
            "competencia": data[:7],
            "publicacao": None, "coleta": coleta,
            "observacao_ou_previsao": "PROJETADO_MODELO" if tipo == "previsao" else "REANALISE_MODELO",
            **linha,
        })
    return {
        "dataset_id": SERIES[tipo], "fonte_id": "OPEN_METEO",
        "latitude_grade": doc["latitude"],
        "longitude_grade": doc["longitude"],
        "latitude_solicitada": esperado_lat,
        "longitude_solicitada": esperado_lon,
        "timezone": "UTC",
        "unidades": UNIDADES.copy(),
        "itens": linhas,
        "quantidade": len(linhas),
        "coleta": coleta,
        "sha256_original": hashlib.sha256(payload).hexdigest(),
        "origem_documentacao": "https://open-meteo.com/en/docs" if tipo == "previsao"
                                 else "https://open-meteo.com/en/docs/historical-weather-api",
        "licenca_dados": "CC BY 4.0 - atribuição obrigatória; free API somente uso não comercial",
        "semantica": "MODELO_ESPACIAL_NAO_ESTACAO",
        "apto_publicacao_automatica": False,
        "apto_backtest_asof_publicacao": False,
        "estado": "NORMALIZADO_OFFLINE_NAO_HOMOLOGADO",
    }
