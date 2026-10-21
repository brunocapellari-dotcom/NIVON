"""Conectores pontuais e read-only para NASA POWER, Open-Meteo e GloFAS.

Gates NIVON: opt-in de rede, hosts fixos, limites de período/tamanho, sem
redirecionamentos, sem API key, sem agendamento ou publicação; não confundir
dados de grade/reanálise e previsões com medições observadas de estação.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener


class ErroHidrometPublico(ValueError):
    """Erro seguro que nunca propaga exceção, URL ou corpo do provedor."""


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NASA = "https://power.larc.nasa.gov/api/temporal/daily/point"
_METEO = "https://api.open-meteo.com/v1/forecast"
_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
_FLOOD = "https://flood-api.open-meteo.com/v1/flood"
_NASA_PARAMS = frozenset({"PRECTOTCORR", "T2M", "T2M_MAX", "T2M_MIN", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN"})
_METEO_DAILY = ("temperature_2m_max", "temperature_2m_min", "precipitation_sum")
_FLOOD_DAILY = "river_discharge"
_MAX_RESPOSTA = 600_000


def _coordenadas(latitude: float, longitude: float) -> tuple[float, float]:
    if (isinstance(latitude, bool) or isinstance(longitude, bool)
            or not isinstance(latitude, (float, int))
            or not isinstance(longitude, (float, int))):
        raise ErroHidrometPublico("coordenadas inválidas")
    lat, lon = float(latitude), float(longitude)
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-34 <= lat <= 6 and -74 <= lon <= -28):
        raise ErroHidrometPublico("consulta deve apontar coordenadas do território brasileiro")
    return lat, lon


def _data(v: str) -> date:
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        raise ErroHidrometPublico("data ISO inválida") from None


def _periodo(inicio: str, fim: str, *, limite: int) -> tuple[date, date]:
    a, b = _data(inicio), _data(fim)
    if a > b or (b - a).days + 1 > limite:
        raise ErroHidrometPublico("intervalo fora do limite")
    return a, b


def _numero(value, *, minimo: float | None = None, maximo: float | None = None):
    if value is None or value == -999 or value == -999.0:
        return None  # missing NASA POWER não é zero
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ErroHidrometPublico("valor não numérico/finito")
    val = float(value)
    if minimo is not None and val < minimo or maximo is not None and val > maximo:
        raise ErroHidrometPublico("valor fora do limite de plausibilidade")
    return val


def _request(url: str, params: dict) -> Request:
    return Request(url + "?" + urlencode(params, safe=","), method="GET",
                   headers={"Accept": "application/json"})


def _buscar(req: Request, *, habilitar_rede=False, transporte=None, timeout=15) -> dict:
    if not habilitar_rede:
        raise PermissionError("rede pública exige habilitação explícita")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 30:
        raise ErroHidrometPublico("timeout fora do contrato")
    client = transporte or build_opener(_SemRedirect)
    try:
        with client.open(req, timeout=timeout) as res:
            if getattr(res, "status", None) != 200:
                raise ErroHidrometPublico("HTTP não validado")
            raw = res.read(_MAX_RESPOSTA + 1)
    except (HTTPError, URLError, OSError):
        raise ErroHidrometPublico("fonte não respondeu com sucesso") from None
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_RESPOSTA:
        raise ErroHidrometPublico("resposta ausente ou grande demais")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise ErroHidrometPublico("JSON inválido") from None
    if not isinstance(value, dict):
        raise ErroHidrometPublico("resposta JSON não é objeto")
    return value


def planejar_nasa_power(*, latitude, longitude, inicio: str, fim: str,
                       parametros=("PRECTOTCORR", "T2M_MAX", "T2M_MIN")) -> Request:
    lat, lon = _coordenadas(latitude, longitude)
    a, b = _periodo(inicio, fim, limite=31)
    pars = tuple(parametros)
    if not 1 <= len(pars) <= 7 or len(set(pars)) != len(pars) or any(x not in _NASA_PARAMS for x in pars):
        raise ErroHidrometPublico("parâmetros POWER fora da allowlist")
    return _request(_NASA, {"parameters": ",".join(pars), "community": "AG",
                           "longitude": lon, "latitude": lat, "start": a.strftime("%Y%m%d"),
                           "end": b.strftime("%Y%m%d"), "format": "JSON",
                           "time-standard": "UTC"})


def normalizar_nasa_power(doc: dict, *, inicio: str, fim: str, parametros: tuple[str, ...]) -> dict:
    a, b = _periodo(inicio, fim, limite=31)
    series = doc.get("properties", {}).get("parameter") if isinstance(doc.get("properties"), dict) else None
    if not isinstance(series, dict) or any(not isinstance(series.get(p), dict) for p in parametros):
        raise ErroHidrometPublico("schema NASA POWER inesperado")
    all_dates = [(a + timedelta(days=i)).strftime("%Y%m%d") for i in range((b - a).days + 1)]
    itens = []
    for key in all_dates:
        linha = {"data_referencia": date.fromisoformat(f"{key[:4]}-{key[4:6]}-{key[6:]}").isoformat()}
        for p in parametros:
            value = series[p].get(key)
            lower = 0 if p in ("PRECTOTCORR", "WS2M", "ALLSKY_SFC_SW_DWN", "RH2M") else -90
            upper = 100 if p == "RH2M" else 1500 if p == "ALLSKY_SFC_SW_DWN" else 500 if p == "PRECTOTCORR" else 150 if p == "WS2M" else 65
            linha[p] = _numero(value, minimo=lower, maximo=upper)
        itens.append(linha)
    return {"fonte": "NASA_POWER", "endpoint": "/api/temporal/daily/point",
            "natureza": "GRADE_SATELITE_REANALISE", "escala_temporal": "DIARIA_UTC",
            "observacao_de_estacao": False, "registros": itens,
            "data_publicacao": None, "data_coleta": None, "homologado": False,
            "publicavel": False, "coleta_agendada": False}


def consultar_nasa_power(*, latitude, longitude, inicio, fim,
                         parametros=("PRECTOTCORR", "T2M_MAX", "T2M_MIN"),
                         habilitar_rede=False, transporte=None) -> dict:
    req = planejar_nasa_power(latitude=latitude, longitude=longitude, inicio=inicio,
                             fim=fim, parametros=parametros)
    doc = _buscar(req, habilitar_rede=habilitar_rede, transporte=transporte)
    out = normalizar_nasa_power(doc, inicio=inicio, fim=fim, parametros=tuple(parametros))
    out["data_coleta"] = datetime.now(timezone.utc).isoformat()
    out["latitude_solicitada"], out["longitude_solicitada"] = _coordenadas(latitude, longitude)
    return out


def planejar_openmeteo(*, latitude, longitude, modo: str, dias: int = 3,
                       inicio: str | None = None, fim: str | None = None) -> Request:
    lat, lon = _coordenadas(latitude, longitude)
    if modo == "previsao":
        if type(dias) is not int or not 1 <= dias <= 7 or inicio is not None or fim is not None:
            raise ErroHidrometPublico("previsão: horizonte 1 a 7 dias")
        return _request(_METEO, {"latitude": lat, "longitude": lon, "daily": ",".join(_METEO_DAILY),
                                "forecast_days": dias, "timezone": "GMT"})
    if modo == "historico":
        if not isinstance(inicio, str) or not isinstance(fim, str):
            raise ErroHidrometPublico("arquivo histórico exige duas datas")
        a, b = _periodo(inicio, fim, limite=31)
        return _request(_ARCHIVE, {"latitude": lat, "longitude": lon, "daily": ",".join(_METEO_DAILY),
                                  "start_date": a.isoformat(), "end_date": b.isoformat(),
                                  "timezone": "GMT"})
    raise ErroHidrometPublico("modo Open-Meteo não suportado")


def _linhas_diarias(doc: dict, parametros: tuple, *, unidades: dict[str, str],
                   limite: int) -> list[dict]:
    obj = doc.get("daily")
    units = doc.get("daily_units")
    if not isinstance(obj, dict) or not isinstance(units, dict):
        raise ErroHidrometPublico("schema daily ausente")
    dates = obj.get("time")
    if not isinstance(dates, list) or not 1 <= len(dates) <= limite or len(set(dates)) != len(dates):
        raise ErroHidrometPublico("datas diárias inválidas")
    for name in parametros:
        if units.get(name) != unidades[name] or not isinstance(obj.get(name), list) or len(obj[name]) != len(dates):
            raise ErroHidrometPublico("unidades ou vetores diários inválidos")
    out=[]
    for i, day in enumerate(dates):
        dt = _data(day)
        row={"data_referencia": dt.isoformat()}
        for name in parametros:
            row[name] = _numero(obj[name][i], minimo=0 if name in ("precipitation_sum", "river_discharge") else -90,
                                maximo=1_000_000 if name == "river_discharge" else 1000 if name == "precipitation_sum" else 65)
        if row.get("temperature_2m_min") is not None and row.get("temperature_2m_max") is not None:
            if row["temperature_2m_min"] > row["temperature_2m_max"]:
                raise ErroHidrometPublico("temperaturas extremas inconsistentes")
        out.append(row)
    return sorted(out, key=lambda x:x["data_referencia"])


def normalizar_openmeteo(doc: dict, *, modo: str, horizonte: int = 7) -> dict:
    if modo not in ("previsao", "historico"):
        raise ErroHidrometPublico("modo inválido")
    out = _linhas_diarias(
        doc, _METEO_DAILY,
        unidades={"temperature_2m_max": "°C", "temperature_2m_min": "°C", "precipitation_sum": "mm"},
        limite=7 if modo=="previsao" else 31)
    return {"fonte": "OPEN_METEO", "fonte_primaria": "MODELOS_CONFORME_METADADOS_API",
            "modo": modo, "natureza": "PROJETADO" if modo=="previsao" else "REANALISE",
            "observacao_de_estacao": False, "registros": out,
            "data_publicacao": None, "data_coleta": None, "homologado": False,
            "publicavel": False, "coleta_agendada": False}


def consultar_openmeteo(*, latitude, longitude, modo="previsao", dias=3,
                        inicio=None, fim=None, habilitar_rede=False, transporte=None):
    req=planejar_openmeteo(latitude=latitude, longitude=longitude, modo=modo,
                           dias=dias, inicio=inicio, fim=fim)
    doc=_buscar(req, habilitar_rede=habilitar_rede, transporte=transporte)
    out=normalizar_openmeteo(doc, modo=modo)
    out["data_coleta"] = datetime.now(timezone.utc).isoformat()
    out["latitude_solicitada"], out["longitude_solicitada"] = _coordenadas(latitude, longitude)
    return out


def planejar_glofas(*, latitude, longitude, dias: int = 7) -> Request:
    lat, lon=_coordenadas(latitude, longitude)
    if type(dias) is not int or not 1 <= dias <= 14:
        raise ErroHidrometPublico("GloFAS: horizonte de piloto até 14 dias")
    return _request(_FLOOD, {"latitude": lat, "longitude": lon, "daily": _FLOOD_DAILY,
                             "forecast_days": dias, "timezone": "GMT"})


def normalizar_glofas(doc: dict) -> dict:
    rows = _linhas_diarias(doc, (_FLOOD_DAILY,), unidades={"river_discharge": "m³/s"}, limite=14)
    if not any(row["river_discharge"] is not None for row in rows):
        raise ErroHidrometPublico("sem cobertura de descarga fluvial neste ponto")
    latitude=doc.get("latitude")
    longitude=doc.get("longitude")
    if (isinstance(latitude, bool) or isinstance(longitude, bool)
            or not isinstance(latitude, (int, float))
            or not isinstance(longitude, (int, float))
            or not math.isfinite(latitude) or not math.isfinite(longitude)):
        raise ErroHidrometPublico("coordenadas da grade GloFAS ausentes")
    return {"fonte": "COPERNICUS_GLOFAS_VIA_OPEN_METEO", "natureza": "PROJETADO",
            "metrica": "VAZAO_MODELO_M3_S", "observacao_de_estacao": False,
            "nao_equivale_nivel_navegavel": True, "grade_latitude": float(latitude),
            "grade_longitude": float(longitude), "registros": rows,
            "data_publicacao": None, "data_coleta": None, "homologado": False,
            "publicavel": False, "coleta_agendada": False}


def consultar_glofas(*, latitude, longitude, dias=7, habilitar_rede=False, transporte=None):
    req = planejar_glofas(latitude=latitude, longitude=longitude, dias=dias)
    doc = _buscar(req, habilitar_rede=habilitar_rede, transporte=transporte)
    result=normalizar_glofas(doc)
    result["data_coleta"] = datetime.now(timezone.utc).isoformat()
    result["latitude_solicitada"], result["longitude_solicitada"] = _coordenadas(latitude, longitude)
    return result
