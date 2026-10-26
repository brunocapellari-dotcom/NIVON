"""Smoke de aceite do Terminal NIVON privado, read-only e opt-in.

Nao realiza deploy, nao consulta cloud por padrao. O operador fornece um
token de identidade efemero via NIVON_TERMINAL_ID_TOKEN, jamais no argv.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPSHandler, HTTPRedirectHandler, build_opener
import argparse
import json
import os
import re
import ssl


class ErroAceite(ValueError):
    pass


class SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _url(url):
    if not isinstance(url, str) or len(url) > 255:
        raise ErroAceite("URL invalida")
    p = urlsplit(url)
    h = p.hostname or ""
    if (p.scheme != "https" or not h.endswith(".run.app")
        or not re.fullmatch(r"[a-z0-9.-]+", h)
        or p.netloc != h or p.path not in ("", "/") or p.query or p.fragment
        or p.username or p.password or p.port):
        raise ErroAceite("somente URL raiz HTTPS de Cloud Run")
    return "https://" + h


def _http(url, *, token=None):
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()),
                          SemRedirect())
    headers = {"Accept": "application/json", "User-Agent": "NIVON-Release-Smoke/1.0"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=headers, method="GET")
    try:
        with opener.open(request, timeout=12) as response:
            if response.headers.get("Content-Length"):
                sz = response.headers["Content-Length"]
                if not sz.isdigit() or int(sz) > 900_000:
                    raise ErroAceite("resposta maior que limite")
            body = response.read(900_001)
            if len(body) > 900_000:
                raise ErroAceite("resposta maior que limite")
            return response.status, dict(response.headers), body
    except HTTPError as exc:
        return exc.code, {}, b""


def _json(body):
    if not isinstance(body, bytes) or not 1 <= len(body) <= 900_000:
        raise ErroAceite("resposta ausente ou excessiva")
    try:
        doc = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ErroAceite("resposta nao JSON") from exc
    if not isinstance(doc, dict):
        raise ErroAceite("JSON nao e objeto")
    return doc


def _auditar_serie(doc, agora):
    if (doc.get("estado") != "ANTT_SERIE_OBSERVADA_DECLARADA"
        or doc.get("natureza") != "OBSERVADO_DECLARADO"
        or doc.get("homologacao_editorial") is not False
        or doc.get("soma_multimodal_permitida") is not False
        or doc.get("point_in_time_historico") is not False
        or doc.get("status_publicacao") != "PREVIA_PRIVADA"):
        raise ErroAceite("estado metodologico inesperado")
    serie = doc.get("serie")
    if not isinstance(serie, list) or not 20 <= len(serie) <= 35 or doc.get("anos") != len(serie):
        raise ErroAceite("serie historica incompleta")
    tu, od = Decimal(0), 0
    for i, row in enumerate(serie):
        if not isinstance(row, dict) or row.get("ano") != 2006 + i:
            raise ErroAceite("serie com ano ausente/duplicado")
        try:
            vol = Decimal(str(row["toneladas_uteis"]))
            quantidade = row["registros"]
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise ErroAceite("indicador ausente") from exc
        comp = row.get("ultima_competencia")
        if (not vol.is_finite() or vol <= 0 or type(quantidade) is not int
            or quantidade <= 0 or not isinstance(comp, str)
            or not re.fullmatch(r"20[0-9]{2}-(?:0[1-9]|1[0-2])", comp)
            or not comp.startswith(str(row["ano"]))):
            raise ErroAceite("ano/volume/competencia inconsistentes")
        if row.get("parcial") is not (i == len(serie)-1 and comp != f"{row['ano']}-12"):
            raise ErroAceite("parcialidade anual inconsistente")
        tu += vol
        od += quantidade
    try:
        esperado = Decimal(str(doc["tu_acumuladas"]))
        ultimo = datetime.fromisoformat(doc["ultima_coleta_utc"])
    except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
        raise ErroAceite("agregados e datas invalidos") from exc
    if (tu != esperado or od != doc.get("registros_acumulados")
        or doc.get("ultima_competencia") != serie[-1]["ultima_competencia"]
        or doc["ultima_competencia"] > agora.strftime("%Y-%m")
        or ultimo.tzinfo is None or ultimo.astimezone(timezone.utc) > agora
        or serie[-1]["ano"] > agora.year):
        raise ErroAceite("totais ou temporalidade invalidos")
    return {"fonte": "ANTT/SIADE", "anos": len(serie),
            "ultima_competencia": doc["ultima_competencia"],
            "homologacao_editorial": False}


def validar(*, url, executar=False, token=None, transporte=None, agora=None):
    raiz = _url(url)
    if type(executar) is not bool:
        raise ErroAceite("modo invalido")
    if not executar:
        return {"estado": "PLANO_SEM_REDE",
                "etapas": ["IAM_NEGAR_ANONIMO", "HEALTHZ_AUTENTICADO",
                           "SERIE_BIGQUERY_AUTENTICADA"],
                "go_live_interno_validado": False}
    if (not isinstance(token, str) or not 30 <= len(token) <= 12000
        or any(c.isspace() for c in token)):
        raise ErroAceite("token de identidade ausente/invalido")
    if transporte is not None and not callable(transporte):
        raise ErroAceite("transporte invalido")
    relogio = agora or datetime.now(timezone.utc)
    if relogio.tzinfo is None:
        raise ErroAceite("relogio sem timezone")
    get = transporte or _http
    anon, _, _ = get(raiz + "/healthz", token=None)
    if anon not in (401, 403):
        raise ErroAceite("servico nao comprovou bloqueio anonimo")
    health, _, body = get(raiz + "/healthz", token=token)
    if health != 200 or _json(body).get("estado") != "PROCESSO_ATIVO":
        raise ErroAceite("processo privado indisponivel")
    status, headers, body = get(raiz + "/api/v1/ferrovia", token=token)
    if (status != 200 or "application/json" not in headers.get("Content-Type", "").lower()
        or headers.get("Cache-Control") != "no-store"):
        raise ErroAceite("API de dados privados indisponivel/insegura")
    fonte = _auditar_serie(_json(body), relogio.astimezone(timezone.utc))
    return {"estado": "SMOKE_REAL_PRIVADO_APROVADO",
            "anonimo_bloqueado": True, "fonte": fonte,
            "go_live_interno_validado": True,
            "go_live_integral_nivon": False, "mutacoes_cloud_executadas": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aceite manual NIVON Cloud Run")
    parser.add_argument("--url", required=True)
    parser.add_argument("--executar", action="store_true")
    args = parser.parse_args(argv)
    try:
        saida = validar(url=args.url, executar=args.executar,
                       token=os.getenv("NIVON_TERMINAL_ID_TOKEN"))
    except (ErroAceite, URLError, TimeoutError, OSError) as exc:
        print(json.dumps({"estado": "BLOQUEADO", "tipo": type(exc).__name__,
                          "go_live_interno_validado": False}))
        return 2
    print(json.dumps(saida, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
