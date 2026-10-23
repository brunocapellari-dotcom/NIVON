"""Aquisição HTTP segura de documentos portuários; BLOQUEADA por padrão.

Não é um scraper universal, não contorna bloqueios e não persiste arquivos.
O operador deve comprovar e registrar direitos por fonte/operação ANTES de habilitar.
"""
from __future__ import annotations

import hashlib
import ipaddress
import socket
from http.client import HTTPSConnection
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import (Request, build_opener, HTTPRedirectHandler,
                            HTTPSHandler, ProxyHandler)


class ErroAquisicao(ValueError):
    pass


class _SemRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None



def _ip_publico_resolvido(dominio: str, *, resolver=None) -> str:
    """Recusa DNS A/AAAA misto ou não-global e retorna um IP para pinning TLS."""
    consultar=resolver if resolver is not None else socket.getaddrinfo
    try:
        registros=consultar(dominio,443,type=socket.SOCK_STREAM)
        enderecos=[registro[4][0] for registro in registros]
        if not enderecos:
            raise ErroAquisicao("dominio sem IP de DNS")
        for ip in enderecos:
            if not ipaddress.ip_address(ip).is_global:
                raise ErroAquisicao("DNS aponta endereco nao publico")
        return enderecos[0]
    except ErroAquisicao:
        raise
    except (OSError, ValueError, IndexError, TypeError, KeyError) as exc:
        raise ErroAquisicao("DNS nao verificavel") from exc


class _ConexaoHTTPSFixada(HTTPSConnection):
    """Conecta no IP DNS aprovado com TLS SNI/certificado do hostname original."""
    def __init__(self, host, *, ip_fixo, **kwargs):
        self._ip_fixo=ip_fixo
        super().__init__(host, **kwargs)

    def connect(self):
        if self._tunnel_host:
            raise ErroAquisicao("proxy/tunel proibido no coletor")
        sock=socket.create_connection(
            (self._ip_fixo,self.port),self.timeout,self.source_address)
        try:
            self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class _HTTPSHandlerFixado(HTTPSHandler):
    """Evita segunda resolucao DNS e restringe HTTPS ao dominio auditado."""
    def __init__(self, dominio: str, ip_fixo: str):
        super().__init__()
        self._dominio=dominio
        self._ip_fixo=ip_fixo

    def https_open(self, req):
        if urlsplit(req.full_url).hostname!=self._dominio:
            raise ErroAquisicao("hostname divergente no HTTPS")
        return self.do_open(
            lambda host, **kwargs: _ConexaoHTTPSFixada(
                host,ip_fixo=self._ip_fixo,**kwargs),
            req,context=self._context,check_hostname=self._check_hostname)


@dataclass(frozen=True)
class FonteWeb:
    fonte_id: str
    url: str
    dominio_autorizado: str
    formato: str
    status_direitos: str = "PENDENTE"
    operacoes_permitidas: frozenset[str] = frozenset()
    limite_bytes: int = 8_000_000

    def verificar(self) -> None:
        if self.status_direitos != "APROVADA" or "COLETA" not in self.operacoes_permitidas:
            raise PermissionError(f"FONTE_WEB_BLOQUEADA: {self.fonte_id}")
        if not self.fonte_id.strip() or not self.dominio_autorizado.strip():
            raise ErroAquisicao("fonte e domínio obrigatórios")
        if (not isinstance(self.url,str) or not isinstance(self.dominio_autorizado,str)
                or len(self.url)>2048 or any(ord(c)<=32 or ord(c)==127 for c in self.url)):
            raise ErroAquisicao("URL oficial malformada ou com controles")
        try:
            parsed=urlsplit(self.url)
            host=parsed.hostname
            porta=parsed.port
        except ValueError as exc:
            raise ErroAquisicao("URL oficial malformada") from exc
        if (parsed.scheme!="https" or parsed.username is not None
                or parsed.password is not None or parsed.fragment
                or porta not in (None,443) or host!=self.dominio_autorizado):
            raise ErroAquisicao("HTTPS/domínio/porta de fonte incompatível")
        if (not host or not host.isascii() or "." not in host
                or host.endswith((".local",".internal",".localhost",".test"))
                or host in {"localhost","localhost.localdomain"}
                or host.startswith(".") or host.endswith(".")
                or any(not label or len(label)>63 or label.startswith("-")
                       or label.endswith("-") for label in host.split("."))):
            raise ErroAquisicao("hostname nao publico ou invalido")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ErroAquisicao("IP literal proibido")
        if self.formato not in ("HTML", "PDF", "CSV", "JSON", "XLSX"):
            raise ErroAquisicao("formato não suportado")
        if not 0 < self.limite_bytes <= 25_000_000:
            raise ErroAquisicao("limite máximo inválido")


def adquirir_fonte(fonte: FonteWeb, *, abridor=None, instante: datetime | None = None,
                   resolver=None) -> dict:
    """Obtém bytes com verificação e hash; SOMENTE quando autorizada.

    Sem abridor injetado: valida TODOS os IPs DNS e fixa o socket no IP aprovado,
    preservando TLS/SNI do dominio original e desabilitando proxies e redirects.
    `abridor` e `resolver` sao dependencias de teste controladas; firewall de
    egress e IAM permanecem controles obrigatorios da infraestrutura.
    """
    fonte.verificar()
    instante = instante or datetime.now(timezone.utc)
    if instante.tzinfo is None:
        raise ErroAquisicao("instante sem timezone")
    if abridor is None:
        ip_aprovado=_ip_publico_resolvido(fonte.dominio_autorizado,resolver=resolver)
        cliente=build_opener(
            ProxyHandler({}),_SemRedirecionar(),
            _HTTPSHandlerFixado(fonte.dominio_autorizado,ip_aprovado))
    else:
        # Testes injetados tambem podem ensaiar o bloqueio de DNS, sem rede.
        if resolver is not None:
            _ip_publico_resolvido(fonte.dominio_autorizado,resolver=resolver)
        cliente=abridor
    req = Request(fonte.url, headers={
        "Accept": "text/html,application/pdf,text/csv,application/json",
        "User-Agent": "NIVON/0.1 (coleta oficial identificada)",
    })
    with cliente.open(req, timeout=20) as response:
        status = int(response.status)
        if status != 200 or response.geturl() != fonte.url:
            raise ErroAquisicao("resposta/redirect diferente da fonte autorizada")
        mime = str(response.headers.get("Content-Type", "")).lower().split(";", 1)[0].strip()
        tipos = {"HTML": {"text/html", "application/xhtml+xml"},
                 "PDF": {"application/pdf"}, "JSON": {"application/json"},
                 "XLSX": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                 "CSV": {"text/csv", "application/csv", "text/plain"}}
        if mime not in tipos[fonte.formato]:
            raise ErroAquisicao("MIME divergente do contrato")
        dados = response.read(fonte.limite_bytes + 1)
        if len(dados) > fonte.limite_bytes or not dados:
            raise ErroAquisicao("payload vazio ou acima do limite")
        if fonte.formato == "XLSX" and not dados.startswith(b"PK\x03\x04"):
            raise ErroAquisicao("assinatura XLSX invalida")
        if fonte.formato == "PDF" and not dados.startswith(b"%PDF"):
            raise ErroAquisicao("assinatura PDF inválida")
        return {
            "fonte_id": fonte.fonte_id,
            "url": fonte.url,
            "capturado_em": instante.astimezone(timezone.utc).isoformat(),
            "mime": mime,
            "sha256": hashlib.sha256(dados).hexdigest(),
            "bytes": len(dados),
            "etag": response.headers.get("ETag"),
            "ultima_modificacao": response.headers.get("Last-Modified"),
            "conteudo": dados,
            "classificacao": "ARQUIVO_COLETADO_NAO_EQUIVALE_DADO_OPERACIONAL_VALIDADO",
        }
