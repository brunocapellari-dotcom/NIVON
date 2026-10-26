"""Adaptadores opcionais de leitura; não são parte do terminal Cloud Run.

Toda saída de terceiros é bruta/não validada até passar nos coletores e nas
regras de publicação próprias do NIVON. Credenciais vêm do ambiente, jamais do Git.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.parse import urlsplit

from .core import (ErroIntegracao, PoliticaIntegracao,
                   dominio_publico_autorizado, evidencia, hash_texto)


MAX_RESPOSTA = 2_000_000


class _SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _json_https_fixo(url, *, chave, metodo="GET", payload=None, opener=None):
    """HTTP restrito: URL montada internamente, JSON limitado e sem redirects."""
    if not url.startswith("https://") or not chave:
        raise ErroIntegracao("HTTPS_E_CHAVE_OBRIGATORIOS")
    corpo = None if payload is None else json.dumps(payload).encode("utf-8")
    if corpo and len(corpo) > 40_000:
        raise ErroIntegracao("REQUISICAO_GRANDE_DEMAIS")
    req = Request(url, data=corpo, method=metodo,
                  headers={"Authorization": "Bearer " + chave,
                           "Accept": "application/json", "Content-Type": "application/json",
                           "User-Agent": "NIVON-integracoes-ia/1"})
    cliente = opener or build_opener(_SemRedirecionamento)
    try:
        with cliente.open(req, timeout=15) as resposta:
            if resposta.status != 200:
                raise ErroIntegracao("SERVICO_HTTP_NAO_OK")
            tipo = resposta.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if tipo != "application/json":
                raise ErroIntegracao("RESPOSTA_NAO_JSON")
            conteudo = resposta.read(MAX_RESPOSTA + 1)
    except (HTTPError, URLError, OSError) as exc:
        # Jamais repassar mensagem do servidor, que pode conter dados sensíveis.
        raise ErroIntegracao("FALHA_SERVICO_EXTERNO") from None
    if len(conteudo) > MAX_RESPOSTA:
        raise ErroIntegracao("RESPOSTA_GRANDE_DEMAIS")
    try:
        return json.loads(conteudo.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ErroIntegracao("JSON_INVALIDO") from None


def consultar_firecrawl(url_fonte: str, politica: PoliticaIntegracao, *, opener=None) -> dict:
    """POST real /v2/scrape; só origem pública expressamente autorizada.

    Retorna texto limitado e proveniência NÃO PUBLICÁVEL; não grava no GCS ou BigQuery.
    """
    politica.permitir_externo()
    url_fonte = dominio_publico_autorizado(url_fonte, politica.dominios_aprovados)
    chave = os.environ.get("FIRECRAWL_API_KEY", "")
    if not chave:
        raise ErroIntegracao("FIRECRAWL_SEM_CHAVE")
    resposta = _json_https_fixo("https://api.firecrawl.dev/v2/scrape", chave=chave,
                                 metodo="POST", payload={"url": url_fonte, "formats": ["markdown"],
                                                         "onlyMainContent": True}, opener=opener)
    dados = resposta.get("data", {}) if isinstance(resposta, dict) else {}
    conteudo = dados.get("markdown") if isinstance(dados, dict) else None
    if resposta.get("success") is not True or not isinstance(conteudo, str) or not conteudo.strip():
        raise ErroIntegracao("FIRECRAWL_SEM_TEXTO_VALIDAVEL")
    if len(conteudo.encode("utf-8")) > MAX_RESPOSTA:
        raise ErroIntegracao("TEXTO_EXTRAIDO_GRANDE_DEMAIS")
    return {"texto": conteudo,
            "evidencia": evidencia(capacidade="firecrawl", origem=url_fonte,
                                   referencia=url_fonte, natureza="EXTRAIDO_NAO_VALIDADO",
                                   valor_sha256=hash_texto(conteudo))}


def listar_paperclip(politica: PoliticaIntegracao, *, opener=None) -> dict:
    """Lê tarefas do Paperclip sem criá-las/alterá-las. GitHub continua canônico."""
    politica.permitir_externo()
    origem = os.environ.get("NIVON_PAPERCLIP_ORIGEM", "")
    identificador = os.environ.get("NIVON_PAPERCLIP_COMPANY_ID", "")
    chave = os.environ.get("PAPERCLIP_API_KEY", "")
    # Não enviar segredos para instalações arbitrárias ou localhost em nuvem.
    dominio_publico_autorizado(origem, politica.dominios_aprovados)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", identificador) or not chave:
        raise ErroIntegracao("PAPERCLIP_SEM_CONFIGURACAO")
    p = urlsplit(origem)
    if p.path not in ("", "/") or p.query or p.fragment:
        raise ErroIntegracao("ORIGEM_PAPERCLIP_DEVE_SER_RAIZ")
    base = origem.rstrip("/")
    url = f"{base}/api/companies/{identificador}/issues?limit=50"
    itens = _json_https_fixo(url, chave=chave, opener=opener)
    if not isinstance(itens, list):
        raise ErroIntegracao("PAPERCLIP_SCHEMA_DIVERGENTE")
    return {"tarefas_externas": [{"id": str(i.get("id", ""))[:100],
                                  "titulo": str(i.get("title", ""))[:200],
                                  "estado_externo": str(i.get("status", ""))[:40]}
                                 for i in itens[:50] if isinstance(i, dict)],
            "canonica": False, "origem": "PAPERCLIP_LEITURA_APENAS"}


def consultar_hindsight(pergunta: str, politica: PoliticaIntegracao, *, cliente=None) -> dict:
    """Recuperação READ-ONLY de memória. Nunca promove fatos automaticamente."""
    politica.permitir_externo()
    banco = os.environ.get("NIVON_HINDSIGHT_BANK_ID", "")
    base = os.environ.get("NIVON_HINDSIGHT_URL", "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", banco) or not 1 <= len(pergunta) <= 500:
        raise ErroIntegracao("MEMORIA_PARAMETROS_INVALIDOS")
    dominio_publico_autorizado(base, politica.dominios_aprovados)
    if not os.environ.get("NIVON_HINDSIGHT_API_KEY"):
        raise ErroIntegracao("HINDSIGHT_SEM_CHAVE")
    if cliente is None:
        try:
            from hindsight_client import Hindsight
        except ImportError:
            raise ErroIntegracao("HINDSIGHT_SDK_AUSENTE") from None
        cliente = Hindsight(base_url=base, api_key=os.environ["NIVON_HINDSIGHT_API_KEY"])
        fechar = True
    else:
        fechar = False
    try:
        resultado = cliente.recall(bank_id=banco, query=pergunta)
        retorno = [{"texto": str(r.text)[:2000]} for r in resultado.results[:20]]
    finally:
        if fechar:
            cliente.close()
    return {"memorias": retorno, "natureza": "MEMORIA_NAO_VALIDADA",
            "validado": False, "publicavel": False}


def consultar_pageindex(pdf: Path, pergunta: str, politica: PoliticaIntegracao, *, cliente=None) -> dict:
    """PageIndex local, somente PDF textual autorizado; LLM remoto exige consentimento.

    Documento permanece no ambiente de execução, mas trechos podem ir para o
    provedor LLM. O comando é opt-in e não participa do deploy do terminal.
    """
    politica.permitir_externo()
    caminho = Path(pdf)
    if (caminho.is_symlink() or not caminho.is_file() or caminho.suffix.lower() != ".pdf"
            or not 1 <= caminho.stat().st_size <= 20_000_000
            or not 1 <= len(pergunta) <= 500):
        raise ErroIntegracao("PDF_OU_PERGUNTA_INVALIDOS")
    if not os.environ.get("NIVON_PAGEINDEX_MODELO") or not os.environ.get("NIVON_PAGEINDEX_CHAT_MODELO"):
        raise ErroIntegracao("MODELOS_PAGEINDEX_AUSENTES")
    if cliente is None:
        try:
            from pageindex import PageIndexClient
        except ImportError:
            raise ErroIntegracao("PAGEINDEX_SDK_AUSENTE") from None
        cliente = PageIndexClient(index=os.environ["NIVON_PAGEINDEX_MODELO"],
                                 chat=os.environ["NIVON_PAGEINDEX_CHAT_MODELO"])
    resposta = cliente.submit_document(str(caminho), wait=True)
    doc_id = resposta.get("doc_id")
    if not isinstance(doc_id, str) or not doc_id:
        raise ErroIntegracao("PAGEINDEX_DOC_ID_AUSENTE")
    conteudo = cliente.chat(pergunta, doc_id=doc_id, stream=False)
    # O texto é uma interpretação do modelo, jamais um valor observado.
    return {"documento_sha256": __import__("hashlib").sha256(caminho.read_bytes()).hexdigest(),
            "doc_id": doc_id, "resposta": str(conteudo)[:20000],
            "natureza": "INFERIDO", "validado": False, "publicavel": False}
