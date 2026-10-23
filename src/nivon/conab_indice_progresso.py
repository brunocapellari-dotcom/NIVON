"""Descoberta controlada de edicoes semanais de progresso de safra CONAB.

Operacao apenas de METADADOS e por execucao explicitamente autorizada.
Nao baixa XLSX/PDF, nao estima datas de publicacao e nao libera consumo LIVE.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

INDICE = ('https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/'
          'safras/progresso-de-safra')
_CAMINHO = '/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra'
_SEMANA = re.compile(r'^Acompanhamento das Lavouras\s*-\s*'
                     r'(\d{2}/\d{2})\s+a\s+(\d{2}/\d{2}/\d{2})\s*$', re.IGNORECASE)
_MAX = 2_000_000


class ErroIndiceConab(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.em_link = False
        self.href = None
        self.partes = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.em_link = True
            self.href = dict(attrs).get('href')
            self.partes = []

    def handle_data(self, data):
        if self.em_link:
            self.partes.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.em_link:
            self.links.append((self.href, ' '.join(''.join(self.partes).split())))
            self.em_link = False
            self.href = None
            self.partes = []


def _url_valida(url: str, *, indice: bool = False) -> bool:
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    if (p.scheme != 'https' or p.hostname != 'www.gov.br'
            or p.username or p.password or p.port not in (None, 443)
            or p.fragment or p.query):
        return False
    return p.path == _CAMINHO if indice else p.path.startswith(_CAMINHO + '/acompanhamento-das-lavouras-')


def extrair_edicoes_indice(raw: bytes, *, origem: str = INDICE,
                          coletado_em: datetime | None = None) -> dict:
    """Retorna paginas CANDIDATAS; os anexos da edicao exigem outro gate."""
    if not _url_valida(origem, indice=True):
        raise ErroIndiceConab('indice nao oficial')
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= _MAX:
        raise ErroIndiceConab('HTML ausente ou grande')
    try:
        html = raw.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ErroIndiceConab('HTML nao UTF-8') from exc
    if '<html' not in html.lower() or not ('Conab' in html or 'conab' in html):
        raise ErroIndiceConab('pagina aparentemente nao oficial ou resposta WAF')
    agora = coletado_em or datetime.now(timezone.utc)
    if not isinstance(agora, datetime) or agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroIndiceConab('coleta sem timezone')
    parser = _Links()
    parser.feed(html)
    vistos = set()
    edicoes = []
    for href, titulo in parser.links:
        m = _SEMANA.fullmatch(titulo)
        if not m or not isinstance(href, str):
            continue
        url = urljoin(origem+'/', href)
        if not _url_valida(url) or url in vistos:
            continue
        vistos.add(url)
        edicoes.append({
            'titulo': titulo,
            'periodo_rotulo': m.group(1)+' a '+m.group(2),
            'pagina_oficial': url,
            'publicado_em': None,
            'arquivo_xlsx': None,
            'estado': 'PAGINA_IDENTIFICADA_NAO_ARQUIVO_VALIDADO',
        })
    return {
        'fonte_id': 'CONAB_PROGR_SAFRA', 'indice': origem,
        'sha256_indice': sha256(raw).hexdigest(),
        'coletado_em': agora.astimezone(timezone.utc).isoformat(timespec='seconds'),
        'edicoes_candidatas': edicoes,
        'estado': 'INDICE_DESCOBERTO_SEM_DOWNLOAD_HOMOLOGADO',
    }


def consultar_indice(*, executar: bool = False, abridor=None,
                      coletado_em: datetime | None = None) -> dict:
    """GET unico do indice; sem navegacao automatica, XLSX ou persistencia."""
    if executar is not True:
        raise PermissionError('consulta CONAB desabilitada por padrao')
    cliente = abridor if abridor is not None else build_opener(ProxyHandler({}), _SemRedirect())
    req = Request(INDICE, headers={'Accept': 'text/html',
                   'User-Agent': 'NIVON/0.1 (pesquisa nao-comercial)'})
    with cliente.open(req, timeout=20) as resp:
        if int(resp.status) != 200 or resp.geturl() != INDICE:
            raise ErroIndiceConab('resposta HTTP ou redirecionamento inesperado')
        mime = str(resp.headers.get('Content-Type','')).split(';',1)[0].strip().lower()
        if mime not in ('text/html','application/xhtml+xml'):
            raise ErroIndiceConab('resposta nao HTML')
        raw = resp.read(_MAX+1)
    return extrair_edicoes_indice(raw, coletado_em=coletado_em)
