"""Contratos fail-closed para ferramentas externas; sem ligações automáticas a serviços.

Importar este pacote nunca aciona rede, modelos, subprocessos ou escrita.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit


class ErroIntegracao(ValueError):
    """Um contrato de segurança ou disponibilidade não foi atendido."""


CAPACIDADES = {
    "skills": {"prioridade": "P0", "tipo": "interno", "pacote": None},
    "aceite": {"prioridade": "P0", "tipo": "interno", "pacote": None},
    "firecrawl": {"prioridade": "P1", "tipo": "api", "pacote": None, "chave": "FIRECRAWL_API_KEY"},
    "magnitude": {"prioridade": "P1", "tipo": "node", "pacote": None},
    "pageindex": {"prioridade": "P1", "tipo": "sdk", "pacote": "pageindex"},
    "graphify": {"prioridade": "P1", "tipo": "arquivo", "pacote": None},
    "hindsight": {"prioridade": "P2", "tipo": "sdk", "pacote": "hindsight_client"},
    "paperclip": {"prioridade": "P2", "tipo": "api", "pacote": None, "chave": "PAPERCLIP_API_KEY"},
    "rtk": {"prioridade": "P2", "tipo": "cli", "binario": "rtk"},
    "llmtrim": {"prioridade": "P2", "tipo": "cli", "binario": "llmtrim"},
    "book_to_skill": {"prioridade": "P2", "tipo": "interno", "pacote": None},
}


@dataclass(frozen=True)
class PoliticaIntegracao:
    habilitar_rede: bool = False
    autorizar_servico_externo: bool = False
    dominios_aprovados: tuple[str, ...] = ()

    def permitir_externo(self) -> None:
        if not (self.habilitar_rede and self.autorizar_servico_externo):
            raise ErroIntegracao("REDE_EXTERNA_NAO_AUTORIZADA")


def _chave_presente(nome: str) -> bool:
    return bool(os.environ.get(nome, "").strip())


def catalogo() -> list[dict]:
    """Catálogo observável: disponível != configurado != testado em produção."""
    return [{"id": nome, "prioridade": v["prioridade"], "tipo": v["tipo"],
             "habilitado": False, "validado_em_producao": False}
            for nome, v in CAPACIDADES.items()]


def diagnostico() -> list[dict]:
    saida = []
    for nome, v in CAPACIDADES.items():
        pacote = v.get("pacote")
        binario = v.get("binario")
        if pacote:
            instalado = importlib.util.find_spec(pacote) is not None
        elif binario:
            instalado = shutil.which(binario) is not None
        elif nome == "magnitude":
            instalado = shutil.which("node") is not None  # Node nao significa que Magnitude esteja instalado
        else:
            instalado = True
        chave = v.get("chave")
        saida.append({"id": nome, "prioridade": v["prioridade"],
                      "dependencia_detectada": instalado,
                      "credencial_presente": _chave_presente(chave) if chave else None,
                      "execucao_externa": "DESATIVADA_POR_PADRAO",
                      "estado": "DISPONIVEL_LOCAL" if v["tipo"] == "interno" else "NAO_VALIDADO"})
    return saida


def dominio_publico_autorizado(url: str, dominios: tuple[str, ...]) -> str:
    """Aceita SOMENTE hostname literal aprovado, HTTPS, sem credenciais ou IPs.

    Destina-se a URLs que serão enviadas a um fornecedor externo, não a um
    browser genérico. DNS/rede devem ter controles de egress adicionais.
    """
    if not isinstance(url, str) or len(url) > 2048:
        raise ErroIntegracao("URL_INVALIDA")
    p = urlsplit(url)
    host = (p.hostname or "").lower().rstrip(".")
    try:
        porta = p.port
    except ValueError:
        raise ErroIntegracao("PORTA_INVALIDA") from None
    if (p.scheme != "https" or not host or p.username or p.password or porta not in (None, 443)
            or p.fragment or any(ord(c) < 32 for c in url)
            or host in ("localhost", "metadata.google.internal") or host.endswith((".internal", ".local"))):
        raise ErroIntegracao("URL_EXTERNA_NAO_PERMITIDA")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ErroIntegracao("IP_LITERAL_NAO_PERMITIDO")
    permitidos = {d.lower().strip().rstrip(".") for d in dominios if d}
    if not permitidos or host not in permitidos or not re.fullmatch(r"[a-z0-9.-]+", host):
        raise ErroIntegracao("DOMINIO_NAO_APROVADO")
    return url


def evidencia(*, capacidade: str, origem: str, referencia: str,
             natureza: str, valor_sha256: str, coleta_em: str | None = None) -> dict:
    if capacidade not in CAPACIDADES:
        raise ErroIntegracao("CAPACIDADE_DESCONHECIDA")
    if natureza not in {"EXTRAIDO_NAO_VALIDADO", "INFERIDO", "OBSERVADO_DECLARADO"}:
        raise ErroIntegracao("NATUREZA_INVALIDA")
    if not re.fullmatch(r"[0-9a-f]{64}", valor_sha256):
        raise ErroIntegracao("HASH_INVALIDO")
    return {"schema": "nivon.integracao.evidencia.v1", "capacidade": capacidade,
            "origem": origem, "referencia": referencia, "natureza": natureza,
            "sha256": valor_sha256,
            "coletado_em": coleta_em or datetime.now(timezone.utc).isoformat(),
            "validado": False, "publicavel": False}


def hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def limitar_contexto(texto: str, *, limite: int = 8000) -> dict:
    """Redução determinística de contexto sem fingir que houve interpretação LLM.

    Retém SHA256 e informa explicitamente quando houve corte, impedindo que
    truncamento silencioso vire base de respostas factuais.
    """
    if not isinstance(texto, str) or not 200 <= limite <= 50000:
        raise ErroIntegracao("LIMITE_CONTEXTO_INVALIDO")
    return {"conteudo": texto[:limite], "truncado": len(texto) > limite,
            "caracteres_originais": len(texto), "sha256_original": hash_texto(texto),
            "nao_usar_como_evidencia_integral": len(texto) > limite}


def salvar_json_atomico(destino: Path, dado: dict) -> None:
    """Saída local explícita de diagnóstico; nunca publicada automaticamente."""
    destino = Path(destino)
    if destino.is_symlink() or destino.exists():
        raise ErroIntegracao("DESTINO_EXISTE_OU_LINK")
    if not destino.parent.is_dir():
        raise ErroIntegracao("DIRETORIO_INEXISTENTE")
    payload = json.dumps(dado, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    if len(payload) > 2_000_000:
        raise ErroIntegracao("RESULTADO_MUITO_GRANDE")
    with destino.open("xb") as f:
        f.write(payload)
