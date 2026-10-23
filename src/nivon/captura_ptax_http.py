"""Captura PTAX HTTP opt-in, transporte isolado e nenhum deploy.

Sem agendamento nem I/O ao importar. Rede só via permitir_rede=True,
com catálogo + direitos explicitamente aprovados. Injeção de transporte
para testes sempre produz origem SINTETICA, não observação REAL_AUTORIZADA.
O relógio local e HTTP Date NÃO são timestamp independente.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import ssl
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener,
)

from .ptax_plano import planejar_consultas_ptax
from .ptax_odata_bruta_mercados import (
    MAX_BYTES, ErroPTAXBruto, _consulta, verificar_ptax_odata_bruta,
)


class ErroCapturaPTAX(ValueError):
    """Falha na autorização, no transporte ou nos metadados HTTP."""


class _SemRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _autorizado(catalogo: Mapping | None, direitos: frozenset[str],
                evidencia: str | None) -> None:
    if not isinstance(catalogo, Mapping) or not isinstance(catalogo.get("datasets"), list):
        raise PermissionError("catálogo PTAX ausente")
    match = [x for x in catalogo["datasets"]
             if isinstance(x, dict) and x.get("id") == "BCB_PTAX"]
    if (len(match) != 1 or match[0].get("enabled") is not True or
            match[0].get("collection_authorized") is not True):
        raise PermissionError("coleta PTAX não habilitada no catálogo")
    if (not isinstance(direitos, frozenset) or
            not {"COLETA", "ARMAZENAMENTO"}.issubset(direitos) or
            not isinstance(evidencia, str) or
            not 6 <= len(evidencia) <= 160 or
            any(x not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:-"
                for x in evidencia)):
        raise PermissionError("evidência de direitos de coleta/armazenamento ausente")


def _requisitar_https(url: str) -> tuple[int, Mapping, bytes]:
    """Um GET, sem cookies, proxy de ambiente, redirect ou retry automático."""
    opener = build_opener(
        ProxyHandler({}),
        HTTPSHandler(context=ssl.create_default_context()),
        _SemRedirecionar(),
    )
    req = Request(
        url, method="GET",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "NIVON-research-offline-optin/0.1",
        },
    )
    try:
        with opener.open(req, timeout=10) as resp:
            return (resp.status, dict(resp.headers.items()),
                    resp.read(MAX_BYTES + 1))
    except (URLError, HTTPError, TimeoutError, OSError) as exc:
        raise ErroCapturaPTAX("requisição oficial não concluída, sem retry") from exc


def _cabecalhos(h: Mapping) -> dict:
    if not isinstance(h, Mapping):
        raise ErroCapturaPTAX("cabeçalhos HTTP inválidos")
    out = {}
    for k, v in h.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ErroCapturaPTAX("cabeçalho inválido")
        nome = k.strip().lower()
        if (not nome or len(nome) > 80 or nome in out or
                len(v) > 512 or "\r" in v or "\n" in v):
            raise ErroCapturaPTAX("cabeçalho HTTP duplicado/inválido")
        out[nome] = v.strip()
    tipo = out.get("content-type", "").split(";", 1)[0].strip().lower()
    if tipo != "application/json":
        raise ErroCapturaPTAX("resposta não é JSON (possível HTML/WAF)")
    if out.get("content-encoding", "identity").lower() != "identity":
        raise ErroCapturaPTAX("codificação HTTP compactada não permitida")
    return out


def _momento_relogio(clock: Callable[[], datetime]) -> str:
    if not callable(clock):
        raise ErroCapturaPTAX("relógio inválido")
    valor = clock()
    if (not isinstance(valor, datetime) or valor.tzinfo is None or
            valor.utcoffset() is None):
        raise ErroCapturaPTAX("relógio sem fuso confiável")
    return valor.astimezone(timezone.utc).isoformat()


def capturar_ptax_odata(
    plano: dict, *, permitir_rede: bool = False,
    catalogo: Mapping | None = None,
    autorizacoes: frozenset[str] = frozenset(),
    evidencia_direitos: str | None = None,
    transporte: Callable[[str], tuple[int, Mapping, bytes]] | None = None,
    relogio: Callable[[], datetime] | None = None,
) -> dict:
    """Obtém snapshot bruto com segurança; permite fixture offline injetada.

    Nunca retorna classe real se a resposta vier de transporte injetado.
    Para fetch real usa HTTPS com validação de certificado padrão do OS;
    o código não certifica disponibilidade/ligação com o BCB histórico.
    """
    if not isinstance(plano, dict) or plano.get("dataset_id") != "BCB_PTAX":
        raise ErroCapturaPTAX("plano BCB_PTAX obrigatório")
    try:
        url = plano["url"]
        moeda = plano["moeda"]
        ini, fim = _consulta(url, moeda)
        esperado = planejar_consultas_ptax(
            moeda=moeda, inicio=ini.isoformat(), fim=fim.isoformat(),
            dias_janela=(fim - ini).days + 1,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ErroCapturaPTAX("plano PTAX inválido") from exc
    if len(esperado) != 1 or esperado[0] != plano:
        raise ErroCapturaPTAX("plano divergente do planejador canônico")
    if type(permitir_rede) is not bool:
        raise ErroCapturaPTAX("permitir_rede precisa ser booleano")
    if transporte is not None and not callable(transporte):
        raise ErroCapturaPTAX("transporte injetado inválido")
    if transporte is not None and permitir_rede:
        raise ErroCapturaPTAX("transporte sintético não pode declarar captura real")
    if transporte is None:
        if not permitir_rede:
            raise PermissionError("HTTP bloqueado por padrão")
        _autorizado(catalogo, autorizacoes, evidencia_direitos)
        obter = _requisitar_https
        origem = "HTTP_HTTPS_BCB_REAL_NAO_HOMOLOGADO"
    else:
        obter = transporte
        origem = "TRANSPORTE_INJETADO_SINTETICO"
    try:
        status, headers, raw = obter(url)
    except ErroCapturaPTAX:
        raise
    except Exception as exc:
        raise ErroCapturaPTAX("falha de transporte injetado") from exc
    if type(status) is not int or status != 200:
        raise ErroCapturaPTAX("resposta HTTP não 200")
    h = _cabecalhos(headers)
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise ErroCapturaPTAX("resposta HTTP maior que limite ou vazia")
    length = h.get("content-length")
    if length is not None and (not length.isdecimal() or
                               int(length) != len(raw)):
        raise ErroCapturaPTAX("Content-Length divergente")
    instante = _momento_relogio(relogio or (lambda: datetime.now(timezone.utc)))
    digest = sha256(raw).hexdigest()
    verificado = verificar_ptax_odata_bruta(
        raw, consulta_url=url, moeda=moeda, coletado_em=instante,
        as_of=instante, raw_sha256_esperado=digest,
    )
    return {
        "estado": "CAPTURA_HTTP_VALIDADA_SEM_PUBLICACAO",
        "origem_execucao": origem,
        "tipo": "REAL_AUTORIZADO" if transporte is None else "SINTETICO",
        "plano": dict(plano), "raw_bytes": raw, "raw_sha256": digest,
        "coletado_em": instante,
        "status_http": status,
        "cabecalhos_http": {
            k: h.get(k) for k in
            ("content-type", "date", "etag", "last-modified", "content-length")
        },
        "verificacao": verificado,
        "fonte_http_certificada_independentemente": False,
        "publicacao_oficial_em": None,
        "publicavel": False,
    }
