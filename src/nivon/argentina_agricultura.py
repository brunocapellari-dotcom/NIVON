"""Coletor controlado de metadados e importador local de estimativas argentinas.

NAO realiza downloads de bases nem agenda tarefas. Identifica recursos oficiais
CKAN, valida CSV licitamente obtido e guarda edicoes distintas em SQLite local.
Sem data de publicacao comprovada, dados nao estao elegiveis a backtests as-of.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

PORTAL = 'datos.magyp.gob.ar'
FONTE = 'ARG_SAGYP_ESTIMACIONES_AGRICOLAS'
# UUIDs publicados nas paginas oficiais dos recursos. A disponibilidade da API
# CKAN NAO foi homologada; a consulta e opt-in e aceita apenas JSON do portal.
RECURSOS = {
    'todos': '95d066e6-8a0f-4a80-b59d-6f28f88eacd5',
    'soja': 'ba694aa3-99d2-4d7d-9936-60f88e36ad9a',
    'milho': '9a6a02f8-ef58-4250-87c2-f639fec502f1',
    'trigo': '50f0edcc-4dfc-4afb-b78a-b164601d36ae',
}
CAMPOS = (
    'cultivo', 'anio', 'campania', 'provincia', 'provincia_id',
    'departamento', 'departamento_id', 'superficie_sembrada_ha',
    'superficie_cosechada_ha', 'produccion_tm', 'rendimiento_kgxha',
)
NUMERICOS = CAMPOS[7:]
MAX_CSV_BYTES = 100_000_000
MAX_METADATA_BYTES = 1_000_000


class ErroArgentina(ValueError):
    """Contrato ou estrutura de fonte nao satisfeitos."""


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def url_recurso(nome: str) -> str:
    if nome not in RECURSOS:
        raise ErroArgentina('recurso nao reconhecido')
    return f'https://{PORTAL}/api/3/action/resource_show?' + urlencode({'id': RECURSOS[nome]})


def _utc(instante: datetime) -> str:
    if not isinstance(instante, datetime) or instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroArgentina('coleta exige instante com timezone')
    return instante.astimezone(timezone.utc).isoformat(timespec='seconds')


def _url_legal(url: str) -> None:
    p = urlsplit(url)
    if p.scheme != 'https' or p.hostname != PORTAL or p.username or p.password or p.fragment or p.port not in (None,443):
        raise ErroArgentina('URL da origem invalida')


def interpretar_metadados(raw: bytes, *, recurso: str, coletado_em: datetime) -> dict:
    """Retorna CANDIDATOS de recursos, nao autorizacao nem CSV coletado."""
    if recurso not in RECURSOS or len(raw) > MAX_METADATA_BYTES:
        raise ErroArgentina('recurso ou tamanho invalidos')
    try:
        doc = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, ValueError) as exc:
        raise ErroArgentina('JSON invalido') from exc
    if not isinstance(doc, dict) or doc.get('success') is not True or not isinstance(doc.get('result'), dict):
        raise ErroArgentina('CKAN nao retornou sucesso')
    result = doc['result']
    if result.get('id') != RECURSOS[recurso]:
        raise ErroArgentina('identidade do recurso divergente')
    arquivo = result.get('url')
    # URLs fornecidas por metadados externos NAO sao abertas automaticamente.
    if not isinstance(arquivo, str) or not arquivo.startswith('https://'):
        raise ErroArgentina('recurso sem URL HTTPS valida')
    formato = str(result.get('format') or '').lower()
    if formato not in {'csv', 'text/csv'}:
        raise ErroArgentina('metadados nao descrevem CSV')
    return {
        'fonte': FONTE, 'recurso': recurso, 'id': result['id'],
        'url_candidata_nao_autorizada': arquivo,
        'portal_url': url_recurso(recurso),
        'licenca_declarada': result.get('license_id'),
        'atualizacao_metadados': result.get('last_modified'),
        'coletado_em': _utc(coletado_em),
        'estado': 'METADADOS_DESCOBERTOS_SEM_DOWNLOAD_HOMOLOGADO',
    }


def consultar_metadados(recurso: str, *, executar: bool = False, abridor=None,
                         coletado_em: datetime | None = None) -> dict:
    """GET de metadados opt-in; sem cookies, proxies de ambiente ou redirects."""
    if executar is not True:
        raise PermissionError('consulta remota exige executar=True')
    url = url_recurso(recurso)
    _url_legal(url)
    cliente = abridor if abridor is not None else build_opener(ProxyHandler({}), _SemRedirect())
    requisicao = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'NIVON/0.1 (pesquisa nao-comercial)'})
    with cliente.open(requisicao, timeout=20) as resp:
        if int(resp.status) != 200 or resp.geturl() != url:
            raise ErroArgentina('HTTP ou redirecionamento invalido')
        mime = str(resp.headers.get('Content-Type', '')).split(';', 1)[0].strip().lower()
        if mime != 'application/json':
            raise ErroArgentina('resposta nao JSON')
        raw = resp.read(MAX_METADATA_BYTES + 1)
        if not 1 <= len(raw) <= MAX_METADATA_BYTES:
            raise ErroArgentina('metadados acima do limite ou vazios')
    r = interpretar_metadados(raw, recurso=recurso, coletado_em=coletado_em or datetime.now(timezone.utc))
    r['hash_metadados'] = sha256(raw).hexdigest()
    return r


def _numero(valor: str) -> str | None:
    s = valor.strip()
    if s in {'', 'NA', 'N/D', 'null', '-'}:
        return None
    if not re.fullmatch(r'\d+(?:[.,]\d+)?', s):
        raise ErroArgentina('valor numerico ambiguo')
    try:
        n = Decimal(s.replace(',', '.'))
    except InvalidOperation as exc:
        raise ErroArgentina('valor decimal invalido') from exc
    if not n.is_finite() or n < 0 or n > Decimal('1000000000000'):
        raise ErroArgentina('valor numerico fora de limites')
    return str(n)


def ler_linhas_csv(conteudo: bytes):
    """CSV oficial com 11 campos documentados; IDs territoriais sao TEXTO."""
    if not isinstance(conteudo, bytes) or not 0 < len(conteudo) <= MAX_CSV_BYTES:
        raise ErroArgentina('arquivo vazio ou excede limite')
    try:
        txt = conteudo.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ErroArgentina('CSV nao UTF-8') from exc
    primeira = txt.partition('\n')[0]
    delimitador = ';' if primeira.count(';') > primeira.count(',') else ','
    leitor = csv.DictReader(StringIO(txt, newline=''), delimiter=delimitador, strict=True)
    if leitor.fieldnames is None or len(leitor.fieldnames) != len(set(leitor.fieldnames)) or not set(CAMPOS) <= set(leitor.fieldnames):
        raise ErroArgentina('cabecalho divergente do contrato')
    for indice, r in enumerate(leitor, start=2):
        if None in r or any(c is None for c in (r.get(x) for x in CAMPOS)):
            raise ErroArgentina(f'CSV irregular na linha {indice}')
        ids = [r[x].strip() for x in ('provincia_id', 'departamento_id')]
        if not all(re.fullmatch(r'\d{1,12}', x) for x in ids):
            raise ErroArgentina(f'ID territorial invalido na linha {indice}')
        try:
            ano = int(r['anio'])
        except ValueError as exc:
            raise ErroArgentina('ano invalido') from exc
        if not 1850 <= ano <= 2100:
            raise ErroArgentina('ano fora dos limites')
        texto = [r[k].strip() for k in ('cultivo', 'campania', 'provincia', 'departamento')]
        if any(not x or len(x) > 160 for x in texto):
            raise ErroArgentina('identidade textual incompleta')
        numeros = {k: _numero(r[k]) for k in NUMERICOS}
        if all(v is None for v in numeros.values()):
            raise ErroArgentina('linha sem indicadores')
        yield {
            'cultivo': texto[0], 'anio': ano, 'campania': texto[1],
            'provincia': texto[2], 'provincia_id': ids[0],
            'departamento': texto[3], 'departamento_id': ids[1],
            **numeros,
        }


_SQL = '''
CREATE TABLE IF NOT EXISTS ar_ediciones (
 edicion_id TEXT PRIMARY KEY, recurso TEXT NOT NULL, sha256 TEXT NOT NULL,
 origen_url TEXT NOT NULL, recogido_utc TEXT NOT NULL, publicado_utc TEXT,
 disponibilidad_verificada INTEGER NOT NULL DEFAULT 0 CHECK(disponibilidad_verificada=0),
 uso TEXT NOT NULL, filas INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ar_estimaciones (
 edicion_id TEXT NOT NULL REFERENCES ar_ediciones(edicion_id),
 cultivo TEXT NOT NULL, anio INTEGER NOT NULL, campania TEXT NOT NULL,
 provincia TEXT NOT NULL, provincia_id TEXT NOT NULL,
 departamento TEXT NOT NULL, departamento_id TEXT NOT NULL,
 superficie_sembrada_ha TEXT, superficie_cosechada_ha TEXT,
 produccion_tm TEXT, rendimiento_kgxha TEXT,
 naturaleza TEXT NOT NULL CHECK(naturaleza='ESTIMADO'),
 PRIMARY KEY (edicion_id,cultivo,campania,provincia_id,departamento_id)
);
CREATE INDEX IF NOT EXISTS ix_ar_estimaciones_safra ON ar_estimaciones (cultivo,campania,provincia_id);
'''


def importar_csv_autorizado(conteudo: bytes, *, banco: str | Path, recurso: str,
                            edicao_id: str, origem_url: str, coletado_em: datetime,
                            direitos_armazenamento_verificados: bool = False) -> dict:
    """Importa snapshot local autorizado, atomicamente, sem promover dados a LIVE.

    O chamador deve reter o RAW de modo privado e imutavel separadamente.
    """
    if direitos_armazenamento_verificados is not True:
        raise PermissionError('direitos de armazenamento nao confirmados')
    if recurso not in RECURSOS or not re.fullmatch(r'[A-Za-z0-9_-]{5,90}', edicao_id):
        raise ErroArgentina('edicao ou recurso invalido')
    _url_legal(origem_url)
    coleta = _utc(coletado_em)
    digest = sha256(conteudo).hexdigest()
    # Arquivos nao devem ser copiados ao repo. A base indexa a versao sem
    # inferir data de publicacao a partir de metadata_modified ou Last-Modified.
    db = sqlite3.connect(str(banco), timeout=30)
    db.execute('PRAGMA foreign_keys=ON')
    try:
        db.executescript(_SQL)
        anterior = db.execute('SELECT sha256,recurso FROM ar_ediciones WHERE edicion_id=?', (edicao_id,)).fetchone()
        if anterior:
            if anterior != (digest, recurso):
                raise ErroArgentina('edicao existente com hash/recurso diferente')
            return {'status': 'DUPLICATA_IDEMPOTENTE', 'edicao_id': edicao_id, 'sha256': digest}
        n = 0
        try:
            with db:
                db.execute('INSERT INTO ar_ediciones VALUES (?,?,?,?,?,?,0,?,?)',
                           (edicao_id,recurso,digest,origem_url,coleta,None,'INTERNO_NAO_COMERCIAL',0))
                for r in ler_linhas_csv(conteudo):
                    db.execute('''INSERT INTO ar_estimaciones VALUES
                        (?,?,?,?,?,?,?,?,?,?,?,?, 'ESTIMADO')''',
                        (edicao_id, r['cultivo'], r['anio'],r['campania'],r['provincia'],r['provincia_id'],
                         r['departamento'],r['departamento_id'],r['superficie_sembrada_ha'],
                         r['superficie_cosechada_ha'],r['produccion_tm'],r['rendimiento_kgxha']))
                    n += 1
                if n == 0:
                    raise ErroArgentina('CSV sem registros')
                db.execute('UPDATE ar_ediciones SET filas=? WHERE edicion_id=?',(n,edicao_id))
        except sqlite3.IntegrityError as exc:
            raise ErroArgentina('observacao duplicada na mesma edicao') from exc
        return {'status':'EDICAO_GUARDADA_EM_QUARENTENA_LOCAL', 'edicao_id':edicao_id,
                'sha256':digest,'linhas':n, 'publicacao':None,
                'disponibilidade_verificada':False, 'publicacao_permitida':False}
    finally:
        db.close()
