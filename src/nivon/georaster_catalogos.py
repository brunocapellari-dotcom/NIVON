"""Metadados ESA WorldCover e JRC Surface Water, sem baixar rasters.

ESA: verifica UMA tile por HEAD (não usa download global).
JRC: lê catálogo WMTS público 2024; imagens RGB servem apenas para mapa,
não para quantificar água ou inferir navegabilidade.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from urllib.request import Request, HTTPRedirectHandler, build_opener
from xml.etree import ElementTree as ET

ESA_ROOT = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
JRC_WMTS = "https://storage.googleapis.com/water-world/downloads_ancillary/WMTS_Global_Surface_WaterV2024.xml"
OWS = "{http://www.opengis.net/ows/1.1}"
WMTS = "{http://www.opengis.net/wmts/1.0}"


class ErroRasterCatalogo(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _utc(t):
    t = t if t is not None else datetime.now(timezone.utc)
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ErroRasterCatalogo("hora sem fuso")
    return t.astimezone(timezone.utc).isoformat()


def planejar_esa(*, latitude: float, longitude: float) -> dict:
    if (type(latitude) not in (float, int) or type(longitude) not in (float, int)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -60 <= latitude < 84 or not -180 <= longitude < 180):
        raise ErroRasterCatalogo("coordenada não suportada na malha ESA")
    sul = int(math.floor(latitude / 3) * 3)
    oeste = int(math.floor(longitude / 3) * 3)
    tile = (("N" if sul >= 0 else "S") + f"{abs(sul):02d}" +
            ("E" if oeste >= 0 else "W") + f"{abs(oeste):03d}")
    filename = f"ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
    return {
        "dataset_id": "ESA_WORLDCOVER_2021_10M", "tile": tile,
        "url": ESA_ROOT + filename, "bbox_tile": [oeste, sul, oeste+3, sul+3],
        "ano_mapa": 2021, "versao": "v200",
        "licenca": "CC_BY_4_0_ATRIBUICAO",
        "natureza": "CLASSIFICACAO_COBERTURA_2021_NAO_LAVOURA_ATUAL",
    }


def consultar_esa_tile(*, latitude: float, longitude: float,
                       executar: bool = False, abridor=None, instante=None) -> dict:
    plano = planejar_esa(latitude=latitude, longitude=longitude)
    if executar is not True:
        raise PermissionError("ESA requer consulta pontual HEAD explícita")
    client = abridor if abridor is not None else build_opener(_NoRedirect())
    req = Request(plano["url"], method="HEAD", headers={"User-Agent": "NIVON/0.1 (nao comercial)"})
    with client.open(req, timeout=15) as response:
        if int(response.status) != 200 or response.geturl() != plano["url"]:
            raise ErroRasterCatalogo("ESA tile ausente, HTTP inválido ou redirect")
        mime = str(response.headers.get("Content-Type", "")).split(";", 1)[0].lower().strip()
        if mime not in ("image/tiff", "image/geotiff", "application/octet-stream", "binary/octet-stream", "image/x-tiff"):
            raise ErroRasterCatalogo("ESA tile MIME inesperado")
        raw_size = response.headers.get("Content-Length")
        if not raw_size or not raw_size.isdecimal() or int(raw_size) <= 0:
            raise ErroRasterCatalogo("ESA size não confiável")
    return {
        **plano, "tamanho_remoto_bytes": int(raw_size),
        "coleta": _utc(instante), "publicacao": None,
        "raster_baixado": False, "raster_existe_por_head": True,
        "estado": "OBJETO_ESA_HEAD_VERIFICADO_SEM_LEITURA_PIXEL",
    }


def normalizar_jrc_wmts(payload: bytes, *, coletado_em: str) -> dict:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 2_000_000:
        raise ErroRasterCatalogo("WMTS vazio ou grande demais")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as e:
        raise ErroRasterCatalogo("WMTS XML inválido") from e
    if root.tag != WMTS + "Capabilities":
        raise ErroRasterCatalogo("não são capacidades WMTS")
    camadas = []
    for layer in root.findall(".//" + WMTS + "Contents/" + WMTS + "Layer"):
        ident = layer.findtext(OWS + "Identifier")
        if ident and len(ident) <= 100:
            camadas.append(ident)
    if not camadas or len(camadas) > 500:
        raise ErroRasterCatalogo("WMTS não contém camadas")
    return {
        "dataset_id": "JRC_GSW_AGUA_SUPERFICIAL",
        "fonte_id": "JRC_GSW", "url_catalogo": JRC_WMTS,
        "camadas_publicas_wmts": sorted(set(camadas)),
        "quantidade_camadas": len(set(camadas)),
        "coleta": coletado_em, "publicacao": None,
        "versao_visualizacao": "2024",
        "sha256_original": hashlib.sha256(payload).hexdigest(),
        "raster_quantitativo_baixado": False,
        "apto_estimativa_vazao": False,
        "natureza": "CAPACIDADES_CARTOGRAFICAS_NAO_HISTORICO_PIXEL_VALIDADO",
        "estado": "WMTS_METADADOS_APENAS",
    }


def consultar_jrc_wmts(*, executar: bool = False, abridor=None, instante=None):
    if executar is not True:
        raise PermissionError("JRC WMTS requer consulta explícita")
    client = abridor if abridor is not None else build_opener(_NoRedirect())
    req = Request(JRC_WMTS, headers={"Accept": "application/xml,text/xml",
                                   "User-Agent": "NIVON/0.1 (nao comercial)"})
    with client.open(req, timeout=20) as response:
        if int(response.status) != 200 or response.geturl() != JRC_WMTS:
            raise ErroRasterCatalogo("JRC HTTP ou redirect inválido")
        mime = str(response.headers.get("Content-Type", "")).split(";", 1)[0].lower().strip()
        if mime not in ("application/xml", "text/xml", "application/vnd.ogc.wmts_xml"):
            raise ErroRasterCatalogo("resposta JRC não é XML")
        blob = response.read(2_000_001)
        if len(blob) > 2_000_000:
            raise ErroRasterCatalogo("WMTS maior que 2MB")
    data = normalizar_jrc_wmts(blob, coletado_em=_utc(instante))
    return {"aquisicao": {"bytes": len(blob), "coleta": data["coleta"],
                          "sha256": data["sha256_original"]}, "dados": data}
