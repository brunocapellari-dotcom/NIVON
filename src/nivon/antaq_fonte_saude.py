"""Monitoramento publicamente acessível da ANTAQ, sem contornar proteções.

Apenas sondas de metadados e páginas pequenas; nunca declara CSV/ZIP
como fonte validada sem download posterior, checksum e prova de schema.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

OFFICIAL_PAGE = "https://estatistica.antaq.gov.br/ea/sense/download.html"
OFFICIAL_ZIP = "https://estatistica.antaq.gov.br/ea/txt/2025.zip"
OFFICIAL_NOTICE = ("https://www.gov.br/antaq/pt-br/central-de-conteudos/"
                   "publicacoes-da-antaq/publicacoes-off/painel-estatistico-aquaviario-indisponivel")
SECONDARY_API = "https://huggingface.co/api/datasets/vinicius-souza/antaq"
KNOWN_SECONDARY = "ff0349fa6dc8cebcec161ee3ce48f6f73f7f3ba8"
_ALLOWED = {OFFICIAL_PAGE, OFFICIAL_ZIP, OFFICIAL_NOTICE, SECONDARY_API}


class SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sondar(url: str, *, metodo: str = "GET", transport=None) -> dict:
    if url not in _ALLOWED or metodo not in ("GET", "HEAD"):
        raise ValueError("URL ou metodo nao autorizado")
    opener = transport or build_opener(SemRedirecionamento)
    request = Request(url, method=metodo, headers={
        "User-Agent": "NIVON-source-health/1.0 (metadata probe)",
        "Accept": "application/json" if url == SECONDARY_API else "*/*",
    })
    try:
        with opener.open(request, timeout=12) as resp:
            status = int(getattr(resp, "status", 200))
            headers = resp.headers
            raw = resp.read(128_001) if metodo == "GET" else b""
    except HTTPError as exc:
        status = int(exc.code)
        headers = exc.headers
        raw = b""
    except (URLError, TimeoutError, OSError):
        return {"url": url, "http_status": None, "estado": "FALHA_REDE"}
    ct = str(headers.get("Content-Type", "")).lower() if headers else ""
    if len(raw) > 128_000:
        return {"url": url, "http_status": status, "estado": "RESPOSTA_EXCESSIVA"}
    if status in (401,403):
        estado = "ACESSO_BLOQUEADO"
    elif status in (301,302,303,307,308):
        alvo = urljoin(url, str(headers.get("Location", ""))) if headers else ""
        estado = ("REDIRECIONAMENTO_PARA_AVISO_OFICIAL"
                  if alvo.split("?",1)[0] == OFFICIAL_NOTICE
                  else "REDIRECIONAMENTO_NAO_SEGUIDO")
    elif status == 404:
        estado = "NAO_LOCALIZADO"
    elif status in (429,500,502,503,504):
        estado = "ERRO_TRANSITORIO"
    elif status != 200:
        estado = "HTTP_NAO_CONFIRMADO"
    elif url == OFFICIAL_ZIP:
        estado = "CANDIDATO_A_DOWNLOAD_OFICIAL" if ("zip" in ct or "octet-stream" in ct) else "FORMATO_NAO_COMPROVADO"
    elif url == OFFICIAL_PAGE:
        txt = raw.decode("utf-8", errors="replace").lower()
        estado = ("AVISO_DE_INDISPONIBILIDADE" if any(
            term in txt for term in ("indisponível", "indisponivel", "em manutenção", "fora do ar"))
                  else "PAGINA_OFICIAL_ACESSIVEL_DOWNLOAD_NAO_VALIDADO")
    elif url == SECONDARY_API:
        if "json" not in ct and raw[:1] != b"{":
            estado = "METADADOS_SECUNDARIOS_INVALIDOS"
        else:
            try:
                j = json.loads(raw)
            except (ValueError, UnicodeError):
                estado = "METADADOS_SECUNDARIOS_INVALIDOS"
            else:
                sha = j.get("sha") if isinstance(j, dict) else None
                if not isinstance(sha, str) or len(sha)!=40 or any(c not in "0123456789abcdef" for c in sha):
                    estado = "METADADOS_SECUNDARIOS_INVALIDOS"
                else:
                    estado = "REPLICA_NOVA_REVISAO_AVALIAR" if sha != KNOWN_SECONDARY else "REPLICA_SEM_REVISAO"
                    return {"url": url, "http_status": status, "estado": estado, "sha": sha}
    else:
        estado = "AVISO_INSTITUCIONAL_ACESSIVEL"
    return {"url": url, "http_status": status, "estado": estado}


def monitorar(*, transport=None, relogio=None) -> dict:
    agora = relogio or datetime.now(timezone.utc)
    return {
        "data_coleta_utc": agora.astimezone(timezone.utc).isoformat(),
        "natureza": "MONITOR_METADADOS_NAO_INGESTAO",
        "sinais": [
            sondar(OFFICIAL_PAGE, transport=transport),
            sondar(OFFICIAL_ZIP, metodo="HEAD", transport=transport),
            sondar(OFFICIAL_NOTICE, metodo="HEAD", transport=transport),
            sondar(SECONDARY_API, transport=transport),
        ],
        "decisao": "NENHUMA_FONTE_E_HOMOLOGADA_POR_STATUS_HTTP",
    }


def main() -> int:
    p=argparse.ArgumentParser(description="Sondas oficiais ANTAQ e frescor da replica")
    p.add_argument("--arquivo", required=True)
    a=p.parse_args()
    doc=monitorar()
    from pathlib import Path
    dest=Path(a.arquivo)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(doc,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
