"""CONAB: resolver um documento /view para um anexo XLSX oficial real.

Fluxo de duas paginas autenticadas por hostname/path e metadados:
edicao semanal -> pagina /view -> link explicito @@download/file.
Nunca constrói URL de anexo por adivinhação, baixa XLSX ou libera uso.
"""
from __future__ import annotations

from datetime import date,datetime,timezone,timedelta
from hashlib import sha256
from html.parser import HTMLParser
import re
import sqlite3
from urllib.parse import urljoin,urlsplit

from .auditoria_publicacao_conab import validar_publicacao_conab
from .conab_fila_publicacoes import _recurso_oficial
from .conab_indice_progresso import ErroIndiceConab,_url_valida

_MAX_HTML=2_000_000
_DOC_RE=re.compile(r'^plantio-e-colheita-\d{2}-\d{2}-a-\d{2}-\d{2}(?:\.xlsx)?$')
_DATE_RE=re.compile(r'Publicado em\s+(\d{2}/\d{2}/\d{4})\s+\d{1,2}h\d{2}',re.I)
_SPAN=re.compile(r'^(\d{2})[-/](\d{2})(?:\s+a\s+|-a-)(\d{2})[-/](\d{2})(?:[-/](\d{2}))?$')
_SCHEMA="""
CREATE TABLE IF NOT EXISTS conab_anexos_resolvidos(
 pagina_semana TEXT NOT NULL,
 url_documento TEXT NOT NULL,
 url_anexo TEXT NOT NULL,
 pagina_publicada_data TEXT NOT NULL,
 hash_html_documento TEXT NOT NULL,
 primeira_coleta_utc TEXT NOT NULL,
 estado TEXT NOT NULL CHECK(estado='LINK_XLSX_DESCOBERTO_NAO_BAIXADO'),
 PRIMARY KEY(pagina_semana,url_documento,url_anexo)
);
"""


class _Ancora(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.aberto=False
        self.href=None
        self.buffer=[]
        self.links=[]
        self.texto=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            self.aberto=True
            self.href=dict(attrs).get('href')
            self.buffer=[]
    def handle_data(self,data):
        self.texto.append(data)
        if self.aberto:self.buffer.append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.aberto:
            self.links.append((self.href,' '.join(''.join(self.buffer).split())))
            self.aberto=False


def _doc_root(url,pagina):
    if not isinstance(url,str) or not _recurso_oficial(url,pagina):
        raise ErroIndiceConab('documento fora da edicao')
    u=urlsplit(url)
    root=u.path.removesuffix('/view').rstrip('/')
    caminho=urlsplit(pagina).path.rstrip('/')+'/'
    nome=root.removeprefix(caminho)
    if not _DOC_RE.fullmatch(nome) or '/' in nome:
        raise ErroIndiceConab('documento CONAB nao e plantio/colheita')
    return 'https://www.gov.br'+root,nome


def _anexo_real(url,root):
    try:u=urlsplit(url)
    except ValueError:return False
    if (u.scheme!='https' or u.hostname!='www.gov.br'
       or u.username or u.password or u.port not in (None,443)
       or u.query or u.fragment):
        return False
    p=urlsplit(root).path
    # URL e EXPLICITAMENTE linkada pelo HTML; nunca sintetizada.
    # Alguns documentos terminam em .xlsx diretamente; os de Plone
    # usam @@download/file sob o documento.
    return u.path==p if p.endswith('.xlsx') else u.path==p+'/@@download/file'


def resolver_html_documento(html:bytes,*,pagina_semana:str,url_documento:str,
                            coletado_em:datetime) -> dict:
    if not _url_valida(pagina_semana):
        raise ErroIndiceConab('edicao fora do indice CONAB')
    root,nome=_doc_root(url_documento,pagina_semana)
    if not isinstance(html,bytes) or not 0<len(html)<=_MAX_HTML:
        raise ErroIndiceConab('HTML documento vazio ou grande')
    if not isinstance(coletado_em,datetime) or coletado_em.tzinfo is None or coletado_em.utcoffset() is None:
        raise ErroIndiceConab('instante de consulta sem timezone')
    try:txt=html.decode('utf-8-sig')
    except UnicodeError as exc:raise ErroIndiceConab('HTML documento nao UTF-8') from exc
    if '<html' not in txt.lower() or 'conab' not in txt.lower():
        raise ErroIndiceConab('documento oficial nao reconhecido')
    parser=_Ancora()
    parser.feed(txt)
    publicados=_DATE_RE.findall(' '.join(parser.texto))
    if len(set(publicados))!=1:
        raise ErroIndiceConab('documento sem uma data de publicacao inequivoca')
    try:
        publicado=datetime.strptime(publicados[0],'%d/%m/%Y').date()
    except ValueError as exc:
        raise ErroIndiceConab('data de publicacao invalida') from exc
    # Esta data e exatamente a declarada no HTML. A hora exibida no
    # portal nao recebe fuso UTC ficticio.
    encontrados=[]
    for href,rotulo in parser.links:
        if not isinstance(href,str) or not rotulo.lower().endswith('.xlsx'):
            continue
        url=urljoin(root+'/',href)
        if _anexo_real(url,root):
            encontrados.append(url)
    urls=sorted(set(encontrados))
    if len(urls)!=1:
        raise ErroIndiceConab('documento sem anexo XLSX unico explicitamente linkado')
    return {'pagina_semana':pagina_semana,'url_documento':url_documento,
            'url_anexo':urls[0],'publicacao_data':publicado.isoformat(),
            'hash_html_documento':sha256(html).hexdigest(),
            'coletado_em_utc':coletado_em.astimezone(timezone.utc).isoformat(timespec='seconds'),
            'estado':'LINK_XLSX_DESCOBERTO_NAO_BAIXADO'}


def _intervalo(rotulo,ano_base):
    m=_SPAN.fullmatch(rotulo)
    if not m:
        raise ErroIndiceConab('intervalo de semana nao reconhecido')
    di,mi,df,mf,yy=m.groups()
    ano_final=2000+int(yy) if yy is not None else ano_base
    try:
        fim=date(ano_final,int(mf),int(df))
        ini=date(ano_final,int(mi),int(di))
        if ini>fim:
            ini=date(ano_final-1,int(mi),int(di))
    except ValueError as exc:
        raise ErroIndiceConab('datas de semana invalidas') from exc
    if (fim-ini).days!=6:
        raise ErroIndiceConab('intervalo semanal nao tem 7 dias')
    return ini,fim


def montar_registro_captura(*,indice_semana:dict,resolucao:dict)->dict:
    """Liga titulo SEMANA + resolucao DOCUMENTO ao contrato de captura V1."""
    try:
        page=indice_semana['pagina_oficial']
        janela=indice_semana['periodo_rotulo']
        if page!=resolucao['pagina_semana']:
            raise ErroIndiceConab('resolucao nao corresponde a semana do indice')
        data_publicacao=date.fromisoformat(resolucao['publicacao_data'])
        inicio,fim=_intervalo(janela,data_publicacao.year)
        docroot,nome=_doc_root(resolucao['url_documento'],page)
        rotulo=nome.removeprefix('plantio-e-colheita-').removesuffix('.xlsx')
        pi,pf=_intervalo(rotulo,fim.year)
    except (KeyError,TypeError,ValueError) as exc:
        raise ErroIndiceConab('evidencia editorial incompleta') from exc
    # A pesquisa de fonte identifica documentos, NAO bytes: SHA ainda NULL.
    reg={
        'id_edicao':'CONAB_PROG_'+fim.strftime('%Y_%m_%d'),
        'url_pagina':page,'url_anexo':resolucao['url_anexo'],
        'publicacao_data':data_publicacao.isoformat(),
        'pagina_inicio':inicio.isoformat(),'pagina_fim':fim.isoformat(),
        'planilha_inicio':pi.isoformat(),'planilha_fim':pf.isoformat(),
        'conteudo_sha256_verificado':None
    }
    validar_publicacao_conab(reg)
    return reg


def registrar_resolucao(db:sqlite3.Connection,*,resolucao:dict) -> dict:
    campos={'pagina_semana','url_documento','url_anexo','publicacao_data',
            'hash_html_documento','coletado_em_utc','estado'}
    if not isinstance(resolucao,dict) or set(resolucao)!=campos:
        raise ErroIndiceConab('contrato do documento incompleto')
    if resolucao['estado']!='LINK_XLSX_DESCOBERTO_NAO_BAIXADO':
        raise ErroIndiceConab('tentativa de promover arquivo sem bytes')
    root,_=_doc_root(resolucao['url_documento'],resolucao['pagina_semana'])
    if not _anexo_real(resolucao['url_anexo'],root):
        raise ErroIndiceConab('anexo nao autorizado')
    if not re.fullmatch(r'[0-9a-f]{64}',resolucao['hash_html_documento']):
        raise ErroIndiceConab('hash da pagina invalido')
    db.executescript(_SCHEMA)
    with db:
        old=db.execute('''SELECT url_anexo,publicacao_data,hash_html_documento
                           FROM conab_anexos_resolvidos WHERE pagina_semana=? AND url_documento=?''',
                       (resolucao['pagina_semana'],resolucao['url_documento'])).fetchone()
        if old and tuple(old)!=(resolucao['url_anexo'],resolucao['publicacao_data'],resolucao['hash_html_documento']):
            raise ErroIndiceConab('documento da mesma URL mudou: requer revisao de versao')
        if not old:
            db.execute('INSERT INTO conab_anexos_resolvidos VALUES (?,?,?,?,?,?,?)',
                       (resolucao['pagina_semana'],resolucao['url_documento'],
                        resolucao['url_anexo'],resolucao['publicacao_data'],
                        resolucao['hash_html_documento'],resolucao['coletado_em_utc'],
                        resolucao['estado']))
    return {'novo':old is None,'status':'DOCUMENTO_OFICIAL_RESOLVIDO_SEM_DOWNLOAD'}
