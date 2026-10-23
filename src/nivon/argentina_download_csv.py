"""Aquisição HTTP controlada de CSV SAGyP: opt-in, sem cron/cloud.

Usar SOMENTE para recurso oficial cuja licença e modalidade de coleta
tenham sido verificadas. Não contorna bloqueios, robots nem redirects.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .argentina_agricultura import MAX_CSV_BYTES, RECURSOS, ErroArgentina, ler_linhas_csv


class _SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_HOSTS = frozenset({'datos.magyp.gob.ar', 'datos.agroindustria.gob.ar'})
_MIMES = frozenset({'text/csv','application/csv','application/octet-stream','application/vnd.ms-excel','text/plain'})


def validar_url_download(url: str, recurso: str) -> None:
    if recurso not in RECURSOS or not isinstance(url,str):
        raise ErroArgentina('recurso nao autorizado')
    try:
        p = urlsplit(url)
    except ValueError as exc:
        raise ErroArgentina('URL de download malformada') from exc
    if (p.scheme!='https' or p.hostname not in _HOSTS or p.port not in (None,443)
            or p.username or p.password or p.query or p.fragment):
        raise ErroArgentina('download exige host publico oficial em HTTPS sem redirecionamentos')
    path = unquote(p.path).lower()
    # Só URLs de arquivo CSV/recurso específico do catalogo: bloqueia endpoints
    # genéricos, caminhos de administracao, URLs arbitrarias e traversals.
    partes = path.split('/')
    if (not path.startswith('/dataset/') or '..' in partes or '\\' in path
            or not (path.endswith('.csv') or RECURSOS[recurso] in path)):
        raise ErroArgentina('URL de recurso SAGyP nao homologavel')
    # A URL e candidata: a identidade vem dos metadados CKAN validados.


def baixar_csv_candidato(*, recurso: str, url: str,
                          executar: bool = False, direitos_coleta_verificados: bool = False,
                          abridor=None, coletado_em: datetime | None = None) -> dict:
    """Uma leitura CSV, no maximo 100MB; nao escreve disco, GitHub ou cloud.

    A entrega fica in-memory; o chamador deve validar, arquivar RAW privado e
    processar via importar_csv_autorizado. 'Dados' NAO sao publicados aqui.
    """
    if executar is not True or direitos_coleta_verificados is not True:
        raise PermissionError('coleta SAGyP exige licenca por operacao e opt-in')
    validar_url_download(url, recurso)
    agora = coletado_em or datetime.now(timezone.utc)
    if not isinstance(agora,datetime) or agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroArgentina('coleta exige timestamp timezone-aware')
    cliente = abridor if abridor is not None else build_opener(ProxyHandler({}),_SemRedirecionamento())
    req = Request(url,headers={'Accept':'text/csv,application/octet-stream',
                  'User-Agent':'NIVON/0.1 (pesquisa agropecuaria nao-comercial)'})
    with cliente.open(req,timeout=40) as resp:
        if int(resp.status)!=200 or resp.geturl()!=url:
            raise ErroArgentina('download HTTP inesperado/redirecionado')
        mime = str(resp.headers.get('Content-Type','')).split(';',1)[0].strip().lower()
        if mime not in _MIMES:
            raise ErroArgentina('recurso nao CSV pelo MIME')
        body = resp.read(MAX_CSV_BYTES+1)
        if not 1<=len(body)<=MAX_CSV_BYTES:
            raise ErroArgentina('CSV vazio ou grande')
    if body.lstrip().lower().startswith((b'<!doctype html',b'<html',b'<?xml')):
        raise ErroArgentina('resposta WAF/HTML/XML, nao CSV')
    # Comprova cabecalho e pelo menos uma linha em fixture/arquivo observado;
    # evita tratar mensagem de erro do site como dados reais.
    linhas = ler_linhas_csv(body)
    try:
        next(linhas)
    except StopIteration as exc:
        raise ErroArgentina('CSV sem observacoes') from exc
    return {
        'recurso': recurso, 'fonte_url': url, 'mime': mime,
        'sha256': sha256(body).hexdigest(), 'bytes': len(body),
        'coletado_em': agora.astimezone(timezone.utc).isoformat(timespec='seconds'),
        'raw': body,
        'estado': 'RAW_OBTIDO_PARA_VALIDACAO_LOCAL_NAO_PUBLICADO',
    }
