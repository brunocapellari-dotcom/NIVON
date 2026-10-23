"""Sondagem HTTP opt-in para SIDRA/Agregados 1092, 1093 e 1094.

Nao agenda, nao persiste payloads, nao infere autorizacao de armazenamento.
Nunca usa URL arbitraria: parametros constroem unicamente enderecos IBGE.
Um HTTP 200/sha nao homologa serie, categorias, direitos ou datas historicas.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .cadeias_adicionais import TABELAS_SIDRA
from .motores import DadoInvalido

_URL_META = "https://servicodados.ibge.gov.br/api/v3/agregados/{}/metadados"
_URL_VALORES = "https://apisidra.ibge.gov.br/values/t/{}/n1/1/p/{}/v/allxp/h/y"


class _SemRedirecionamentos(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _requisicao_https(url, *, timeout, limite):
    """Transporte sem proxies, redirects, cookies, retries ou hosts externos."""
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()),
                          _SemRedirecionamentos())
    req = Request(url, headers={"Accept": "application/json",
                                "User-Agent": "NIVON-SIDRA-Discovery/1.0"}, method="GET")
    with opener.open(req, timeout=timeout) as resposta:
        estado = resposta.status
        tipo = resposta.headers.get("Content-Type", "").lower()
        tamanho = resposta.headers.get("Content-Length")
        if tamanho and (not tamanho.isdigit() or int(tamanho) > limite):
            raise DadoInvalido("Content-Length excede limite ou nao numerico")
        corpo = resposta.read(limite + 1)
    if len(corpo) > limite:
        raise DadoInvalido("resposta acima do limite")
    return {"status_http": estado, "content_type": tipo, "corpo": corpo}


def _inspecionar(resposta, *, tabela, tipo, limite):
    if not isinstance(resposta, dict):
        raise DadoInvalido("transporte nao retornou objeto")
    status = resposta.get("status_http")
    ct = resposta.get("content_type")
    bruto = resposta.get("corpo")
    if status != 200:
        raise DadoInvalido("HTTP distinto de 200")
    if not isinstance(ct, str) or "json" not in ct.lower():
        raise DadoInvalido("Content-Type nao JSON")
    if not isinstance(bruto, bytes) or len(bruto) > limite or not bruto:
        raise DadoInvalido("payload ausente ou grande demais")
    try:
        doc = json.loads(bruto.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise DadoInvalido("JSON invalido") from exc
    if tipo == "metadados":
        if not isinstance(doc, dict) or str(doc.get("id", "")) != tabela:
            raise DadoInvalido("metadados de outra tabela")
        linhas = 1
    else:
        if not isinstance(doc, list) or len(doc) < 2 or not isinstance(doc[0], dict) or any(
            not isinstance(linha, dict) for linha in doc[1:]
        ):
            raise DadoInvalido("estrutura values invalida")
        if "V" not in doc[0]:
            raise DadoInvalido("cabecalho values nao contem V")
        linhas = len(doc) - 1
    return {"status": "FORMATO_PRELIMINAR_CONFIRMADO", "http_status": status,
            "sha256": sha256(bruto).hexdigest(), "bytes": len(bruto),
            "linhas": linhas, "autenticidade_historica": False,
            "mapeamento_homologado": False, "direitos_homologados": False}


def sondar_sidra_abate(*, especie, periodo, rede=False, timeout=8, transporte=None):
    """Inspeciona metadados + valores nacionais de um trimestre.

    Sem rede, devolve plano. Transporte injetado destina-se so a teste: nunca
    produzir status de observacao real quando o transporte e simulado.
    """
    if especie not in TABELAS_SIDRA:
        raise DadoInvalido("especie desconhecida")
    if not isinstance(periodo, str) or not re.fullmatch(r"(?:19|20)\d{2}0[1-4]", periodo):
        raise DadoInvalido("periodo deve ser AAAA0T")
    ano = int(periodo[:4])
    if ano < 1997:
        raise DadoInvalido("periodo anterior ao SIDRA")
    if type(rede) is not bool or type(timeout) not in (int, float) or isinstance(timeout, bool) or not 1 <= timeout <= 10:
        raise DadoInvalido("rede/timeout invalidos")
    # Nao sondar trimestre ainda nao encerrado.
    inicio_proximo = datetime(ano + (periodo[-1] == "4"), 1 if periodo[-1] == "4" else 3 * int(periodo[-1]) + 1, 1,
                             tzinfo=timezone.utc)
    if rede and inicio_proximo > datetime.now(timezone.utc):
        raise DadoInvalido("nao requisitar trimestre futuro ou aberto")
    if transporte is not None and not callable(transporte):
        raise DadoInvalido("transporte invalido")
    tabela = TABELAS_SIDRA[especie]
    urls = {"metadados": _URL_META.format(tabela),
            "valores": _URL_VALORES.format(tabela, periodo)}
    modo = "SIMULACAO" if transporte is not None else "HTTPS_DIRETO" if rede else "PLANEJADO_SEM_REDE"
    if not rede and transporte is None:
        return {"especie": especie, "tabela_sidra": tabela, "periodo": periodo,
                "modo": modo, "urls": urls, "resultados": {},
                "rede_executada": False, "homologado": False}
    resultados = {}
    for tipo, url in urls.items():
        limite = 1_000_000 if tipo == "metadados" else 2_000_000
        try:
            res = (transporte(url=url, timeout=timeout, limite=limite)
                   if transporte is not None else
                   _requisicao_https(url, timeout=timeout, limite=limite))
            resultados[tipo] = _inspecionar(res, tabela=tabela, tipo=tipo, limite=limite)
        except (HTTPError, URLError, TimeoutError, OSError, DadoInvalido,
                ValueError) as exc:
            resultados[tipo] = {"status": "ERRO_NAO_HOMOLOGADO",
                                "motivo": type(exc).__name__,
                                "detalhe": str(exc)[:180]}
    return {"especie": especie, "tabela_sidra": tabela, "periodo": periodo,
            "modo": modo, "urls": urls, "resultados": resultados,
            "rede_executada": bool(rede and transporte is None),
            "homologado": False}


def sondar_tres_cadeias(*, periodo, rede=False, timeout=8, transporte=None):
    return {"status": "DIAGNOSTICO_SEM_HOMOLOGACAO",
            "cadeias": [sondar_sidra_abate(
                especie=esp, periodo=periodo, rede=rede, timeout=timeout,
                transporte=transporte) for esp in ("BOVINO", "SUINO", "FRANGO")]}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sondagem limitada SIDRA (sem gravacao)")
    parser.add_argument("--periodo", required=True, help="trimestre AAAA0T")
    parser.add_argument("--rede", action="store_true", help="opt-in de 6 consultas oficiais")
    args = parser.parse_args()
    print(json.dumps(sondar_tres_cadeias(periodo=args.periodo, rede=args.rede),
                     ensure_ascii=False, indent=2))
