"""Downloader oficial ANTAQ com URLs fixas e direitos bloqueados por padrão.

Não contorna WAF, reCAPTCHA, TLS, redirects ou credenciais. A API somente
recebe arquivos ZIP públicos quando a licença da operação foi homologada.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .lineup_nacional import instante
from .antaq_historico_offline import ErroAntaq, MAX_ZIP_BYTES


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class DireitosAntaq:
    status: str = "PENDENTE"
    operacoes: frozenset[str] = frozenset()
    evidencia_id: str | None = None

    def verificar(self) -> None:
        if (self.status != "APROVADA" or
            not {"LEITURA", "COLETA", "ARMAZENAMENTO"}.issubset(self.operacoes) or
            not self.evidencia_id):
            raise PermissionError("ANTAQ: autorização documentada para coleta e armazenamento ausente")


def endpoint_antaq(*, tipo: str, ano: int | None = None, em: str) -> str:
    hoje=instante(em)
    if tipo not in ("ANUAL", "MERCADORIAS"):
        raise ErroAntaq("tipo de ZIP não suportado")
    if tipo=="MERCADORIAS":
        if ano is not None:
            raise ErroAntaq("cadastro de mercadorias não possui ano")
        return "https://estatistica.antaq.gov.br/ea/txt/Mercadoria.zip"
    if isinstance(ano,bool) or not isinstance(ano,int) or not 2010<=ano<=hoje.year:
        raise ErroAntaq("ano de descarga fora da competência permitida")
    return f"https://estatistica.antaq.gov.br/ea/txt/{ano}.zip"


def adquirir_arquivo_antaq(*, tipo: str, direitos: DireitosAntaq, em: str,
                           ano: int | None = None, abridor=None) -> dict:
    """Aceita mocks em testes; nunca retorna 'fonte atualizada' só porque HTTP 200."""
    direitos.verificar()
    url=endpoint_antaq(tipo=tipo,ano=ano,em=em)
    cliente=abridor if abridor is not None else build_opener(_SemRedirect())
    requisicao=Request(url,headers={"Accept":"application/zip,application/octet-stream",
                                     "User-Agent":"NIVON/0.1 (coleta governamental documentada)"})
    try:
        with cliente.open(requisicao,timeout=35) as resp:
            if resp.status != 200 or resp.geturl()!=url:
                raise ErroAntaq("URL redirecionada ou resposta não homologada")
            mime=str(resp.headers.get("Content-Type","")).lower().split(";")[0].strip()
            if mime not in {"application/zip","application/octet-stream","application/x-zip-compressed"}:
                raise ErroAntaq("resposta não é ZIP (WAF, HTML ou MIME inválido)")
            payload=resp.read(MAX_ZIP_BYTES+1)
    except (HTTPError,URLError,TimeoutError) as exc:
        raise ErroAntaq("fonte ANTAQ indisponível; não contornar restrições") from exc
    if not isinstance(payload,bytes) or not payload.startswith(b"PK\x03\x04"):
        raise ErroAntaq("conteúdo ANTAQ não corresponde a arquivo ZIP")
    if len(payload)>MAX_ZIP_BYTES:
        raise ErroAntaq("ZIP ANTAQ acima do limite seguro")
    return {
        "url":url,"tipo":tipo,"ano":ano,
        "coletado_em":instante(em).isoformat(),
        "hash_sha256":hashlib.sha256(payload).hexdigest(),
        "bytes":len(payload),"conteudo":payload,
        "classificacao":"ZIP_OBTIDO_NAO_HOMOLOGA_REGISTROS_NEM_REDISTRIBUICAO",
    }
