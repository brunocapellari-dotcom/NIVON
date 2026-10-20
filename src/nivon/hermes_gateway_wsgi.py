"""WSGI read-only gateway for Hermes -> NIVON, denied without OIDC verifier.

No server is started on import. Production must configure a trusted HTTPS
ingress/reverse proxy, allowlisted service subjects, audience, outbound
policy and rate limits. Tokens are never logged or persisted.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from .hermes_adapter import NivonProjectAdapter, ErroIntegracaoHermes


class ErroGateway(ValueError):
    pass


def verificar_oidc_google(token: str, audience: str) -> Mapping[str, Any]:
    """Real Google signature+expiry+audience verification, optional dependency.

    Only call from configured ingress. This does not fetch credentials from user
    payload. google-auth is needed in the runtime environment, not core tests.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token
    except ImportError as exc:
        raise PermissionError("verificador OIDC não instalado") from exc
    try:
        verified = id_token.verify_token(token, Request(), audience=audience)
    except Exception as exc:
        raise PermissionError("token OIDC não autenticado") from exc
    if not isinstance(verified, dict):
        raise PermissionError("resposta OIDC inválida")
    return verified


def _out(start_response, status: str, body: dict) -> list[bytes]:
    encoded=json.dumps(body, ensure_ascii=False,
                       separators=(",",":"), allow_nan=False).encode("utf-8")
    start_response(status,[
        ("Content-Type","application/json; charset=utf-8"),
        ("Content-Length",str(len(encoded))),
        ("Cache-Control","no-store"),
        ("Pragma","no-cache"),
        ("X-Content-Type-Options","nosniff"),
        ("Referrer-Policy","no-referrer"),
    ])
    return [encoded]


def criar_gateway_hermes(*, audience: str,
                        sujeitos_permitidos: frozenset[str],
                        fabrica_adaptador: Callable[[str], NivonProjectAdapter],
                        verificar: Callable[[str,str],Mapping[str, Any]] = verificar_oidc_google):
    """Return WSGI callable, configured from trusted application control plane.

    Test stubs can inject a verifier; production MUST use cryptographic OIDC
    verification and preapproved service accounts. No execute endpoint exists.
    """
    if not isinstance(audience,str) or not 5<=len(audience)<=512 or not audience.strip():
        raise ErroGateway("audiência de serviço obrigatória")
    if (not isinstance(sujeitos_permitidos,frozenset)
        or not 1<=len(sujeitos_permitidos)<=100
        or any(not isinstance(s,str) or not 3<=len(s)<=256 for s in sujeitos_permitidos)):
        raise ErroGateway("lista explícita de identidades obrigatória")
    if not callable(fabrica_adaptador) or not callable(verificar):
        raise ErroGateway("fábrica e verificador OIDC obrigatórios")

    def application(environ, start_response):
        route=environ.get("PATH_INFO")
        method=environ.get("REQUEST_METHOD")
        if route!="/v1/nivon/query":
            return _out(start_response,"404 Not Found",{"status":"ROTA_INEXISTENTE"})
        if method!="POST":
            return _out(start_response,"405 Method Not Allowed",{"status":"METODO_BLOQUEADO"})
        ctype=environ.get("CONTENT_TYPE","").split(";",1)[0].strip().lower()
        if ctype!="application/json":
            return _out(start_response,"415 Unsupported Media Type",{"status":"JSON_OBRIGATORIO"})
        header=environ.get("HTTP_AUTHORIZATION")
        if (not isinstance(header,str) or len(header)>12_000
            or not header.startswith("Bearer ")
            or not re.fullmatch(r"[A-Za-z0-9._~-]{20,12000}",header[7:])):
            return _out(start_response,"401 Unauthorized",{"status":"IDENTIDADE_NAO_AUTENTICADA"})
        try:
            claims=verificar(header[7:],audience)
            if not isinstance(claims,Mapping):
                raise PermissionError("identidade inválida")
            # Issuer and audience are checked again even when verifier stubs are
            # supplied, so only a REAL verifier can unlock production safely.
            if (claims.get("iss") not in {"accounts.google.com","https://accounts.google.com"}
                or claims.get("aud")!=audience
                or claims.get("sub") not in sujeitos_permitidos
                or not isinstance(claims.get("sub"),str)):
                raise PermissionError("OIDC issuer/audience/subject mismatch")
        except Exception:
            return _out(start_response,"403 Forbidden",{"status":"ACESSO_NEGADO"})
        try:
            n=int(environ.get("CONTENT_LENGTH","-1"))
        except (ValueError,TypeError):
            return _out(start_response,"411 Length Required",{"status":"TAMANHO_INVALIDO"})
        if not 0<n<=65_536:
            return _out(start_response,"413 Content Too Large",{"status":"TAMANHO_INVALIDO"})
        stream=environ.get("wsgi.input")
        if stream is None:
            return _out(start_response,"400 Bad Request",{"status":"CORPO_AUSENTE"})
        try:
            raw=stream.read(n)
            if not isinstance(raw,bytes) or len(raw)!=n:
                raise ErroGateway("corpo incompleto")
            item=json.loads(raw)
            if (not isinstance(item,dict)
                or set(item)!={"capability","payload"}
                or not isinstance(item["capability"],str)
                or not isinstance(item["payload"],dict)):
                raise ErroGateway("contrato de query inválido")
            # Raw data from an external Hermes mission is never allowed to
            # choose a DB path, permission, destination, secret or tool.
            adapter=fabrica_adaptador(claims["sub"])
            if not isinstance(adapter,NivonProjectAdapter):
                raise ErroGateway("adaptador de identidade não configurado")
            answer=asyncio.run(adapter.query(item["capability"],item["payload"]))
            payload=json.dumps(answer,ensure_ascii=False,allow_nan=False).encode("utf-8")
            if len(payload)>131_072:
                raise ErroGateway("resposta superior a 128 KiB")
        except (ValueError,TypeError,KeyError,UnicodeError,json.JSONDecodeError,ErroIntegracaoHermes):
            return _out(start_response,"400 Bad Request",{"status":"CONSULTA_INVALIDA"})
        except PermissionError:
            return _out(start_response,"403 Forbidden",{"status":"ACESSO_NEGADO"})
        except Exception:
            return _out(start_response,"503 Service Unavailable",{"status":"BACKEND_INDISPONIVEL"})
        return _out(start_response,"200 OK",{"status":"CONSULTA_READ_ONLY","result":answer})

    return application
