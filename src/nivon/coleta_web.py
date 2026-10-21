"""Aquisição HTTP segura de documentos portuários; BLOQUEADA por padrão.

Não é um scraper universal, não contorna bloqueios e não persiste arquivos.
O operador deve comprovar e registrar direitos por fonte/operação ANTES de habilitar.
"""
from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ErroAquisicao(ValueError):
    pass


class _SemRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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
        if (not isinstance(self.url, str) or not isinstance(self.dominio_autorizado, str)
                or any(ord(c) <= 32 or ord(c) == 127 for c in self.url)
                or len(self.url) > 2048):
            raise ErroAquisicao("URL oficial inválida ou com controles")
        try:
            parsed = urlsplit(self.url)
            host = parsed.hostname
            porta = parsed.port
        except ValueError as exc:
            raise ErroAquisicao("URL oficial malformada") from exc
        if (parsed.scheme != "https" or parsed.username is not None
                or parsed.password is not None or parsed.fragment
                or porta not in (None, 443)
                or host != self.dominio_autorizado):
            raise ErroAquisicao("HTTPS/domínio/porta de fonte incompatível")
        if (not host or not host.isascii() or "." not in host
                or host in {"localhost", "localhost.localdomain"}
                or host.endswith((".localhost", ".local", ".internal", ".test"))
                or host.startswith(".") or host.endswith(".")
                or any(not label or len(label) > 63 or label.startswith("-")
                       or label.endswith("-") for label in host.split("."))):
            raise ErroAquisicao("endereço local ou host público inválido")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ErroAquisicao("IP literal proibido")
        if self.formato not in ("HTML", "PDF", "CSV", "JSON", "XML"):
            raise ErroAquisicao("formato não suportado")
        if not 0 < self.limite_bytes <= 20_000_000:
            raise ErroAquisicao("limite máximo inválido")


def adquirir_fonte(fonte: FonteWeb, *, abridor=None, instante: datetime | None = None) -> dict:
    """Obtém bytes com verificação e hash; SOMENTE quando autorizada.

    `abridor` permite testar respostas sintéticas sem rede. DNS/TLS/egress
    ainda requerem controles de infraestrutura antes de operação real.
    """
    fonte.verificar()
    instante = instante or datetime.now(timezone.utc)
    if instante.tzinfo is None:
        raise ErroAquisicao("instante sem timezone")
    cliente = abridor if abridor is not None else build_opener(_SemRedirecionar())
    req = Request(fonte.url, headers={
        "Accept": "text/html,application/pdf,text/csv,application/json,application/rss+xml,application/atom+xml,application/xml",
        "User-Agent": "NIVON/0.1 (coleta oficial identificada)",
    })
    with cliente.open(req, timeout=20) as response:
        status = int(response.status)
        if status != 200 or response.geturl() != fonte.url:
            raise ErroAquisicao("resposta/redirect diferente da fonte autorizada")
        mime = str(response.headers.get("Content-Type", "")).lower().split(";", 1)[0].strip()
        tipos = {"HTML": {"text/html", "application/xhtml+xml"},
                 "PDF": {"application/pdf"}, "JSON": {"application/json"}, "CSV": {"text/csv", "application/csv", "text/plain"},
                 "XML": {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}}
        if mime not in tipos[fonte.formato]:
            raise ErroAquisicao("MIME divergente do contrato")
        dados = response.read(fonte.limite_bytes + 1)
        if len(dados) > fonte.limite_bytes or not dados:
            raise ErroAquisicao("payload vazio ou acima do limite")
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
