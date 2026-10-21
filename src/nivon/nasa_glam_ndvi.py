"""NASA/USDA GIMMS GLAM gettbl v4: aquisição manual de NDVI.

A API fornece tabelas CSV de VIIRS/OLCI, não produtividade observada.
IDs ADM são IDs do GLAM, não códigos municipais IBGE. Máscara de culturas
precisa ser previamente homologada; ausência significa máscara default.
Não realiza download em massa, persistência nem publicações.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = "https://glam1.gsfc.nasa.gov/api/gettbl/v4"
SENSORES = frozenset(("VNP", "VJ1", "OS3"))
MODOS = frozenset(("seasonal", "historical"))
VERSAO = "v17"


class ErroGLAM(ValueError):
    pass


class _NaoRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def planejar_ndvi(*, id_glam: str, ano: int, sensor: str = "VNP",
                  inicio_mes: int = 1, meses: int = 12, modo: str = "seasonal") -> str:
    if not isinstance(id_glam, str) or not re.fullmatch(r"[0-9]{1,12}", id_glam):
        raise ErroGLAM("identificador GLAM/ADM inválido; não use código IBGE")
    if sensor not in SENSORES or modo not in MODOS:
        raise ErroGLAM("satélite/tipo de série não homologado")
    if (type(ano) is not int or not 2013 <= ano <= 2100 or
            type(inicio_mes) is not int or not 1 <= inicio_mes <= 12 or
            type(meses) is not int or not 1 <= meses <= 12 or
            inicio_mes + meses > 13):
        raise ErroGLAM("ano/meses inválidos")
    params = {"sat": sensor, "version": VERSAO, "layer": "NDVI",
              "shape": "ADM", "ids": id_glam, "ts_type": modo,
              "years": str(ano), "start_month": str(inicio_mes),
              "num_months": str(meses), "format": "csv"}
    return BASE + "?" + urlencode(params)


def _coleta(valor):
    if not isinstance(valor, str):
        raise ErroGLAM("coleta sem data")
    try:
        t = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroGLAM("coleta inválida") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ErroGLAM("coleta sem timezone")
    return t.astimezone(timezone.utc).isoformat()


def normalizar_csv_ndvi(payload: bytes, *, id_glam: str, ano: int, sensor: str,
                       inicio_mes: int, meses: int, modo: str,
                       coletado_em: str) -> dict:
    url = planejar_ndvi(id_glam=id_glam, ano=ano, sensor=sensor,
                       inicio_mes=inicio_mes, meses=meses, modo=modo)
    coleta = _coleta(coletado_em)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 2_000_000:
        raise ErroGLAM("CSV vazio ou acima do limite")
    try:
        s = payload.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ErroGLAM("CSV não UTF-8") from exc
    if "\x00" in s or "<html" in s[:200].lower():
        raise ErroGLAM("dados CSV inválidos/HTML disfarçado")
    leitor = csv.reader(io.StringIO(s, newline=""))
    linhas = list(leitor)
    if not 2 <= len(linhas) <= 5_001:
        raise ErroGLAM("CSV sem linhas ou excede 5 mil")
    cab = linhas[0]
    if (not 2 <= len(cab) <= 100 or len(set(cab)) != len(cab) or
            any(not c.strip() or len(c) > 120 for c in cab)):
        raise ErroGLAM("cabeçalho CSV inválido")
    if any(len(linha) != len(cab) for linha in linhas[1:]):
        raise ErroGLAM("linhas CSV desalinhadas")
    if not any(any(v.strip() for v in linha) for linha in linhas[1:]):
        raise ErroGLAM("série CSV sem observações")
    # Não converter para NDVI numérico antes de confirmar versão/layout real.
    return {
        "dataset_id": "NASA_USDA_GLAM_NDVI", "fonte_id": "NASA_GLAM",
        "origem_url": url, "identificador_area_glam": id_glam,
        "codigo_ibge": None, "ano_solicitado": ano,
        "sensor": sensor, "tipo_serie": modo,
        "inicio_mes": inicio_mes, "quantidade_meses": meses,
        "cabecalho_original": cab,
        "linhas_textuais": [dict(zip(cab, linha)) for linha in linhas[1:]],
        "n_linhas": len(linhas) - 1,
        "natureza": "INDICE_VERDEJAMENTO_SATELITE_NAO_PRODUTIVIDADE",
        "mascara_culturas_homologada": False,
        "valores_ndvi_normalizados": False,
        "publicacao": None, "referencia": None, "competencia": None,
        "coleta": coleta, "sha256_original": hashlib.sha256(payload).hexdigest(),
        "apto_motor_produtividade": False, "apto_publicacao_automatica": False,
        "estado": "CSV_NASA_GLAM_SCHEMA_REAL_PENDENTE",
    }


def consultar_ndvi(*, id_glam: str, ano: int, sensor: str = "VNP",
                   inicio_mes: int = 1, meses: int = 12, modo: str = "seasonal",
                   executar: bool = False, abridor=None, instante=None):
    url = planejar_ndvi(id_glam=id_glam, ano=ano, sensor=sensor,
                       inicio_mes=inicio_mes, meses=meses, modo=modo)
    if executar is not True:
        raise PermissionError("CONSULTA_PONTUAL_DESATIVADA")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "glam1.gsfc.nasa.gov"
            or parsed.path != "/api/gettbl/v4" or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment):
        raise ErroGLAM("host/caminho não permitido")
    agora = instante if instante is not None else datetime.now(timezone.utc)
    if not isinstance(agora, datetime) or agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroGLAM("data de coleta exige timezone")
    cliente = abridor if abridor is not None else build_opener(_NaoRedirecionar())
    req = Request(url, headers={"Accept": "text/csv,text/plain",
                                "User-Agent": "NIVON/0.1 (pesquisa-nao-comercial)"})
    with cliente.open(req, timeout=20) as resp:
        if int(resp.status) != 200 or resp.geturl() != url:
            raise ErroGLAM("HTTP/redirect não autorizado")
        mime = str(resp.headers.get("Content-Type", "")).split(";", 1)[0].lower().strip()
        if mime not in ("text/csv", "application/csv", "text/plain"):
            raise ErroGLAM("MIME não é CSV")
        payload = resp.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ErroGLAM("CSV excedeu tamanho")
    out = normalizar_csv_ndvi(payload, id_glam=id_glam, ano=ano,
                             sensor=sensor, inicio_mes=inicio_mes, meses=meses,
                             modo=modo, coletado_em=agora.isoformat())
    return {"dados": out, "aquisicao": {"sha256": out["sha256_original"],
             "bytes": len(payload), "coleta": out["coleta"], "mime": mime}}
