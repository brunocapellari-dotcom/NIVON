"""Cliente pontual de APIs públicas NIVON: transporte HTTPS real, SEM agenda.

Os parsers científicos existentes continuam autoritativos: este módulo só
adquire uma resposta autorizada explicitamente, limita volume, verifica host,
MIME, redirecionamentos e passa bytes para normalização offline. Nenhuma série
é persistida ou publicada; catálogo de produção continua default-deny.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .open_meteo_publico import planejar_consulta, normalizar_diario
from .bcb_sgs_selic import URL_PONTUAL, normalizar_selic_diaria
from .bcb_focus_odata import planejar_focus, normalizar_focus
from .ibge_municipios import ENDPOINT as IBGE_URL, normalizar_municipios_ibge
from .nasa_power_diario import planejar_power, normalizar_power_diario
from .banco_mundial_indicadores import planejar_indicador, normalizar_indicador


class ErroAPIPublica(ValueError):
    pass


class _NaoRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Somente endpoints construídos por funções validadas, nunca URL do usuário.
_DESTINOS = {
    "open_forecast": ("api.open-meteo.com", "/v1/forecast", 2_000_000),
    "open_archive": ("archive-api.open-meteo.com", "/v1/archive", 2_000_000),
    "bcb_selic": ("api.bcb.gov.br", "/dados/serie/bcdata.sgs.11/dados/ultimos/1", 250_000),
    "bcb_focus": ("olinda.bcb.gov.br", "/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais", 1_000_000),
    "worldbank": ("api.worldbank.org", "/v2/country/BR/indicator/", 500_000),
    "ibge": ("servicodados.ibge.gov.br", "/api/v1/localidades/municipios", 8_000_000),
    "nasa_power": ("power.larc.nasa.gov", "/api/temporal/daily/point", 2_000_000),
    "open_flood": ("flood-api.open-meteo.com", "/v1/flood", 750_000),
    "open_ensemble": ("ensemble-api.open-meteo.com", "/v1/ensemble", 1_500_000),
    "fao_fpma_catalog": ("fpma.fao.org", "/giews/v4/global/price_module/api/v1/FpmaSerie/", 800_000),
    "fao_fpma_prices": ("fpma.fao.org", "/giews/v4/global/price_module/api/v1/FpmaSeriePrice/", 800_000),
}


def _obter_json(url: str, *, recurso: str, executar: bool, abridor=None,
                instante: datetime | None = None) -> dict:
    """Uma requisição; não há retries, varredura, paginação nem cron implícito."""
    if executar is not True:
        raise PermissionError("Somente consulta pontual explícita; fontes em produção permanecem OFF")
    if recurso not in _DESTINOS:
        raise ErroAPIPublica("recurso não homologado")
    host, caminho, limite = _DESTINOS[recurso]
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != host
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment):
        raise ErroAPIPublica("domínio HTTPS divergente da fonte oficial")
    if ((recurso == "worldbank" and not parsed.path.startswith(caminho)) or
            (recurso != "worldbank" and parsed.path != caminho)):
        raise ErroAPIPublica("caminho de API divergente do contrato")
    if not parsed.query and recurso not in ("ibge",):
        raise ErroAPIPublica("parâmetros obrigatórios ausentes")
    instante = instante if instante is not None else datetime.now(timezone.utc)
    if not isinstance(instante, datetime) or instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroAPIPublica("hora de coleta exige timezone")
    cliente = abridor if abridor is not None else build_opener(_NaoRedirecionar())
    pedido = Request(url, headers={"Accept": "application/json",
                                    "User-Agent": "NIVON/0.1 pesquisa-nao-comercial"})
    with cliente.open(pedido, timeout=15) as resposta:
        if int(resposta.status) != 200 or resposta.geturl() != url:
            raise ErroAPIPublica("resposta HTTP/redirect não autorizado")
        tipo = str(resposta.headers.get("Content-Type", "")).split(";", 1)[0].lower().strip()
        if tipo not in ("application/json", "application/geo+json"):
            raise ErroAPIPublica("resposta não é JSON do serviço")
        corpo = resposta.read(limite + 1)
        if not isinstance(corpo, bytes) or not 1 <= len(corpo) <= limite:
            raise ErroAPIPublica("payload vazio ou acima do limite")
    return {"url": url, "bytes": corpo,
            "sha256": hashlib.sha256(corpo).hexdigest(),
            "coleta": instante.astimezone(timezone.utc).isoformat(),
            "tamanho": len(corpo), "mime": tipo}


def consultar_open_meteo(*, latitude: float, longitude: float,
                         tipo: str = "previsao", inicio: str | None = None,
                         fim: str | None = None, dias_previsao: int = 7,
                         executar: bool = False, abridor=None,
                         instante: datetime | None = None) -> dict:
    url = planejar_consulta(latitude=latitude, longitude=longitude,
                           tipo=tipo, inicio=inicio, fim=fim,
                           dias_previsao=dias_previsao)
    raw = _obter_json(url, recurso="open_forecast" if tipo == "previsao" else "open_archive",
                     executar=executar, abridor=abridor, instante=instante)
    resultado = normalizar_diario(raw["bytes"], tipo=tipo, coletado_em=raw["coleta"],
                                 latitude_solicitada=latitude,
                                 longitude_solicitada=longitude)
    return {"aquisição": {k: v for k, v in raw.items() if k != "bytes"}, "dados": resultado}


def consultar_selic(*, executar: bool = False, abridor=None,
                    instante: datetime | None = None) -> dict:
    raw = _obter_json(URL_PONTUAL, recurso="bcb_selic", executar=executar,
                     abridor=abridor, instante=instante)
    resultado = normalizar_selic_diaria(raw["bytes"], coletado_em=raw["coleta"])
    return {"aquisição": {k: v for k, v in raw.items() if k != "bytes"}, "dados": resultado}


def consultar_banco_mundial(*, indicador: str, inicio: int, fim: int,
                           executar: bool = False, abridor=None,
                           instante: datetime | None = None) -> dict:
    url = planejar_indicador(indicador=indicador, inicio=inicio, fim=fim)
    raw = _obter_json(url, recurso="worldbank", executar=executar,
                     abridor=abridor, instante=instante)
    resultado = normalizar_indicador(raw["bytes"], indicador=indicador,
                                   inicio=inicio, fim=fim, coletado_em=raw["coleta"])
    return {"aquisição": {k: v for k, v in raw.items() if k != "bytes"}, "dados": resultado}


def consultar_ibge_municipios(*, executar: bool = False, abridor=None,
                             instante: datetime | None = None) -> dict:
    raw = _obter_json(IBGE_URL, recurso="ibge", executar=executar,
                     abridor=abridor, instante=instante)
    resultado = normalizar_municipios_ibge(raw["bytes"], coletado_em=raw["coleta"],
                                          consulta_url=raw["url"])
    return {"aquisição": {k: v for k, v in raw.items() if k != "bytes"}, "dados": resultado}


def consultar_nasa_power(*, latitude: float, longitude: float,
                         inicio: str, fim: str, executar: bool = False,
                         abridor=None, instante: datetime | None = None) -> dict:
    plano = planejar_power(latitude=latitude, longitude=longitude,
                          inicio=inicio, fim=fim)
    raw = _obter_json(plano["url"], recurso="nasa_power", executar=executar,
                     abridor=abridor, instante=instante)
    resultado = normalizar_power_diario(bytes_json=raw["bytes"], plano=plano,
                                       sha256=raw["sha256"], coletado_em=raw["coleta"])
    return {"aquisição": {k: v for k, v in raw.items() if k != "bytes"}, "dados": resultado}


def consultar_focus(*, indicador: str, inicio: str, fim: str,
                    max_itens: int = 200, executar: bool = False,
                    abridor=None, instante: datetime | None = None) -> dict:
    """Consulta 31 dias de expectativas anuais de mercado, sem credenciais."""
    url = planejar_focus(indicador=indicador, inicio=inicio, fim=fim,
                         max_itens=max_itens)
    raw = _obter_json(url, recurso="bcb_focus", executar=executar,
                      abridor=abridor, instante=instante)
    out = normalizar_focus(raw["bytes"], indicador=indicador, inicio=inicio,
                          fim=fim, max_itens=max_itens, coletado_em=raw["coleta"])
    return {"aquisição": {k: v for k, v in raw.items() if k != "bytes"}, "dados": out}
