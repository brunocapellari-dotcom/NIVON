"""Descoberta CONAB indice -> pagina semanal -> recursos e fila incremental.

Camada exclusivamente de metadados: NUNCA baixa XLSX, nao atribui data
de publicacao a uma pagina e nao promulga observacoes a motores do NIVON.
As edicoes entram em fila SQLite de QUARENTENA, para uma etapa posterior
de captura/parse aprovada. Proveniencia preservada por digest do HTML.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urljoin, urlsplit

from .conab_indice_progresso import ErroIndiceConab, _url_valida

_LIMITE = 2_000_000
_RECURSOS = {
    "PLANTIO_COLHEITA": re.compile(r'^Plantio e Colheita(?:\s+\d{2}[-/]\d{2}\s+a\s+\d{2}[-/]\d{2})?(?:\.xlsx)?$',re.I),
    "FENOLOGIA": re.compile(r'^Fenologia das Lavouras(?:\s+\d{2}[-/]\d{2}\s+a\s+\d{2}[-/]\d{2})?(?:\.xlsx)?$',re.I),
    "MONITORAMENTO": re.compile(r'^Monitoramento das Condi[cç][oõ]es das Lavouras(?:\.pdf)?$',re.I),
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS conab_semanas_descobertas (
 pagina_url TEXT PRIMARY KEY, titulo TEXT NOT NULL,
 periodo_rotulo TEXT NOT NULL, primeiro_visto_utc TEXT NOT NULL,
 ultimo_visto_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conab_documentos_candidatos (
 pagina_url TEXT NOT NULL REFERENCES conab_semanas_descobertas(pagina_url),
 tipo TEXT NOT NULL, url TEXT NOT NULL, rotulo TEXT NOT NULL,
 hash_html_edicao TEXT NOT NULL, descoberto_em_utc TEXT NOT NULL,
 fase TEXT NOT NULL CHECK(fase='PENDENTE_VALIDACAO'),
 PRIMARY KEY(pagina_url,tipo,url)
);
CREATE TABLE IF NOT EXISTS conab_observacoes_indice (
 indice_sha256 TEXT NOT NULL, coletado_utc TEXT NOT NULL,
 qtd_semanas INTEGER NOT NULL, PRIMARY KEY(indice_sha256,coletado_utc)
);
CREATE TABLE IF NOT EXISTS conab_url_indice_historico (
 pagina_canonica TEXT NOT NULL, url_observada TEXT NOT NULL,
 indice_sha256 TEXT NOT NULL, primeira_coleta_utc TEXT NOT NULL,
 PRIMARY KEY(pagina_canonica,url_observada,indice_sha256)
);
CREATE INDEX IF NOT EXISTS idx_conab_doc_fase ON conab_documentos_candidatos(fase);
"""


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[]
        self._href=None
        self._texto=[]
        self._ativo=False

    def handle_starttag(self,tag,attrs):
        if tag.lower()=='a':
            self._ativo=True
            self._href=dict(attrs).get('href')
            self._texto=[]

    def handle_data(self,dado):
        if self._ativo:
            self._texto.append(dado)

    def handle_endtag(self,tag):
        if tag.lower()=='a' and self._ativo:
            self.links.append((self._href,' '.join(''.join(self._texto).split())))
            self._ativo=False
            self._href=None
            self._texto=[]


def _utc(value: str) -> str:
    try:
        d=datetime.fromisoformat(value.replace('Z','+00:00'))
    except (AttributeError,ValueError) as exc:
        raise ErroIndiceConab('instante da descoberta invalido') from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroIndiceConab('instante sem timezone')
    return d.astimezone(timezone.utc).isoformat(timespec='seconds')


def _recurso_oficial(url:str,pagina:str) -> bool:
    try:
        u=urlsplit(url)
        p=urlsplit(pagina)
    except ValueError:
        return False
    if (u.scheme!='https' or u.hostname!='www.gov.br' or u.port not in (None,443)
            or u.username or u.password or u.query or u.fragment):
        return False
    # O recurso deve pertencer a propria edicao. A CONAB pode publicar
    # nomes do segundo segmento que nao coincidem com o titulo da pagina.
    prefixo=p.path.rstrip('/')+'/'
    return u.path.startswith(prefixo) and not any(part in ('.','..') for part in u.path.split('/'))


def examinar_pagina_semana(raw: bytes, *, pagina_url: str) -> dict:
    """Extrai apenas LINKS candidatos oficiais. Nunca presume XLSX recebido."""
    if not _url_valida(pagina_url):
        raise ErroIndiceConab('pagina semanal fora do portal')
    if not isinstance(raw,bytes) or not 1<=len(raw)<=_LIMITE:
        raise ErroIndiceConab('HTML de edicao vazio ou excedente')
    try:
        texto=raw.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ErroIndiceConab('HTML da edicao nao UTF-8') from exc
    if '<html' not in texto.lower() or 'Conab' not in texto and 'conab' not in texto:
        raise ErroIndiceConab('conteudo nao reconhecido como pagina CONAB')
    p=_Links()
    p.feed(texto)
    encontrados={}
    for href,rotulo in p.links:
        tipo=next((k for k,r in _RECURSOS.items() if r.fullmatch(rotulo)),None)
        if not tipo or not isinstance(href,str):
            continue
        url=urljoin(pagina_url.rstrip('/')+'/',href)
        if not _recurso_oficial(url,pagina_url):
            continue
        # Versoes diferentes de uma mesma categoria sao permitidas somente
        # em URLs distintas: ambas seguem para revisao de um operador.
        encontrados[(tipo,url)]={
            'tipo':tipo,'rotulo':rotulo,'url_candidata':url,
            'formato_esperado':'PDF' if tipo=='MONITORAMENTO' else 'XLSX',
            'bytes_comprovados':False,
            'publicado_em':None,'estado':'LINK_SEM_BYTES_HOMOLOGADOS',
        }
    saida=list(encontrados.values())
    return {
        'pagina_url':pagina_url,'sha256_html':sha256(raw).hexdigest(),
        'recursos':saida,
        'estado':'CANDIDATOS_SEM_RECURSO_VALIDADO',
    }


def atualizar_fila(db:sqlite3.Connection, *, indice:dict,
                  paginas:dict[str,bytes]) -> dict:
    """Etapa local independente de rede; recebe indice e HTML de edicoes.

    A transacao so e confirmada se TODAS as paginas informadas forem validas.
    Atualizacoes nao apagam candidatas anteriores (versoes permanecem visiveis).
    """
    if not isinstance(indice,dict) or indice.get('fonte_id')!='CONAB_PROGR_SAFRA':
        raise ErroIndiceConab('indice fora do contrato')
    coleta=_utc(indice.get('coletado_em'))
    semanas=indice.get('edicoes_candidatas')
    if not isinstance(semanas,list) or len(semanas)>500:
        raise ErroIndiceConab('lista de edicoes invalida')
    lista={}
    for semana in semanas:
        if (not isinstance(semana,dict) or not _url_valida(semana.get('pagina_oficial',''))
                or not isinstance(semana.get('titulo'),str) or not isinstance(semana.get('periodo_rotulo'),str)):
            raise ErroIndiceConab('semana inconsistente no indice')
        url=semana['pagina_oficial']
        if url in lista and lista[url]!=semana:
            raise ErroIndiceConab('edicao duplicada com metadados conflitantes')
        lista[url]=semana
    if not isinstance(paginas,dict) or not set(paginas)<=set(lista):
        raise ErroIndiceConab('HTML sem pagina descoberta correspondente')
    hash_indice=indice.get('sha256_indice')
    if not isinstance(hash_indice,str) or not re.fullmatch(r'[0-9a-f]{64}',hash_indice):
        raise ErroIndiceConab('hash do indice ausente')
    analisados={k:examinar_pagina_semana(v,pagina_url=k) for k,v in paginas.items()}
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript(_SCHEMA)
    novas_semanas=0
    novos_links=0
    with db:
        db.execute('INSERT OR IGNORE INTO conab_observacoes_indice VALUES (?,?,?)',
                   (hash_indice,coleta,len(lista)))
        for url,item in lista.items():
            observada=item.get('url_observada_indice',url)
            if not _url_valida(observada):
                raise ErroIndiceConab('link originalmente observado fora do indice')
            db.execute('''INSERT OR IGNORE INTO conab_url_indice_historico
                          VALUES (?,?,?,?)''',(url,observada,hash_indice,coleta))
            row=db.execute('SELECT titulo,periodo_rotulo FROM conab_semanas_descobertas WHERE pagina_url=?',(url,)).fetchone()
            if row is None:
                db.execute('INSERT INTO conab_semanas_descobertas VALUES(?,?,?,?,?)',
                           (url,item['titulo'],item['periodo_rotulo'],coleta,coleta))
                novas_semanas+=1
            else:
                if tuple(row)!=(item['titulo'],item['periodo_rotulo']):
                    raise ErroIndiceConab('semana com titulo/periodo alterado')
                db.execute('UPDATE conab_semanas_descobertas SET ultimo_visto_utc=? WHERE pagina_url=?',
                           (coleta,url))
        for url,info in analisados.items():
            for candidato in info['recursos']:
                existe=db.execute('SELECT hash_html_edicao,rotulo FROM conab_documentos_candidatos WHERE pagina_url=? AND tipo=? AND url=?',
                                  (url,candidato['tipo'],candidato['url_candidata'])).fetchone()
                if existe is not None:
                    # mudança do HTML da página não muda os bytes do recurso;
                    # guardar primeira descoberta como trilha de auditoria.
                    if existe[1]!=candidato['rotulo']:
                        raise ErroIndiceConab('rotulo de recurso mudou sem nova URL')
                    continue
                db.execute('INSERT INTO conab_documentos_candidatos VALUES (?,?,?,?,?,?,?)',
                           (url,candidato['tipo'],candidato['url_candidata'],candidato['rotulo'],
                            info['sha256_html'],coleta,'PENDENTE_VALIDACAO'))
                novos_links+=1
    return {
        'novas_semanas':novas_semanas,'novos_recursos_candidatos':novos_links,
        'semanas_conhecidas':len(lista),'paginas_examinadas':len(analisados),
        'estado':'FILA_LOCAL_SEM_ACESSO_A_XLSX',
    }


def proximos_arquivos(db:sqlite3.Connection, *, limite:int=20) -> list[dict]:
    """Lista para coletor existente da CONAB; NAO aciona aquisicao."""
    if type(limite) is not int or not 1<=limite<=100:
        raise ErroIndiceConab('limite invalido')
    db.row_factory=sqlite3.Row
    db.executescript(_SCHEMA)
    rows=db.execute('''SELECT pagina_url,tipo,url,rotulo,descoberto_em_utc
                        FROM conab_documentos_candidatos
                        WHERE fase='PENDENTE_VALIDACAO'
                        ORDER BY descoberto_em_utc DESC,pagina_url,tipo
                        LIMIT ?''',(limite,)).fetchall()
    return [dict(r) for r in rows]
