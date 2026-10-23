"""SIO Granos — exportacoes publicas sob controle de acesso e esquema.

A pagina publica intervalo maximo de 180 dias para consulta de operacoes.
Este modulo PLANEJA janelas e importa CSV previamente obtido com autorizacao,
desde que o contrato de colunas tenha sido verificado por fonte real.
NUNCA baixa dados, faz login, reproduz sessao ASP.NET ou ativa coleta em rede.

Uma operacao SIO nao equivale a entrega fisica, frete nem exportacao realizada.
"""
from __future__ import annotations

import csv
from datetime import date,datetime,timezone,timedelta
from decimal import Decimal,InvalidOperation
from hashlib import sha256
from io import StringIO
import hmac
import json
import re
import sqlite3
from urllib.parse import urlsplit

PORTAL='https://www.siogranos.com.ar/Consulta_publica/operaciones_informadas_exportar.aspx'
CAMPOS_REQUERIDOS=frozenset({'id_operacao','data_concertacao','produto','toneladas'})
CAMPOS_OPCIONAIS=frozenset({'provincia_origem','moeda','preco_por_tonelada'})
REGISTRO='OPERACAO_DECLARADA_SIO_NAO_COMPROVA_ENTREGA'
MAX_BYTES=35_000_000
MAX_ROWS=180_000


class ErroSIO(ValueError):
    pass


def planejar_periodos(inicio:str,fim:str,*,dias_por_janela:int=90)->list[dict]:
    """Divide consultas inclusivas sem sobreposicao, limite oficial de 180 dias."""
    if type(dias_por_janela) is not int or not 1<=dias_por_janela<=180:
        raise ErroSIO('intervalo deve conter 1 a 180 dias')
    try:
        ini=date.fromisoformat(inicio)
        fim_=date.fromisoformat(fim)
    except (ValueError,TypeError) as exc:
        raise ErroSIO('datas YYYY-MM-DD obrigatorias') from exc
    if not date(1990,1,1)<=ini<=fim_<=date(2100,12,31):
        raise ErroSIO('periodo fora dos limites')
    if (fim_-ini).days>365*20:
        raise ErroSIO('horizonte de consulta exagerado')
    janelas=[]
    cursor=ini
    while cursor<=fim_:
        ponta=min(cursor+timedelta(days=dias_por_janela-1),fim_)
        janelas.append({
            'inicio':cursor.isoformat(),'fim':ponta.isoformat(),
            'consulta_url':PORTAL,'metodo':'EXPORTACAO_PUBLICA_SUPERVISIONADA',
            'status':'AGUARDA_EXPORTACAO_AUTORIZADA',
        })
        cursor=ponta+timedelta(days=1)
    return janelas


def _data(valor:str) -> str:
    t=str(valor or '').strip()
    try:
        d=datetime.strptime(t,'%d/%m/%Y').date()
    except ValueError as exc:
        raise ErroSIO('fecha concertacion deve estar em DD/MM/YYYY') from exc
    if not date(1990,1,1)<=d<=date(2100,12,31):
        raise ErroSIO('data SIO fora de limites')
    return d.isoformat()


def _decimal(valor:str, *, moeda:bool=False) -> str:
    t=str(valor or '').strip().replace(' ','')
    if not t:
        if moeda:
            return ''
        raise ErroSIO('quantidade de toneladas ausente')
    # Exige formatação argentina (pontos de milhar opcionais, vírgula decimal).
    if not re.fullmatch(r'(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,6})?',t):
        raise ErroSIO('numero SIO fora de locale es-AR ou ambiguo')
    n=Decimal(t.replace('.','').replace(',','.'))
    if not n.is_finite() or n<0 or n>Decimal('100000000000000'):
        raise ErroSIO('quantidade ou preco invalido')
    if not moeda and n==0:
        raise ErroSIO('operacao nao pode ter toneladas zero')
    return format(n,'f')


def _normalizar_csv(arquivo:bytes, *, colunas:dict, chave_hmac:bytes) -> list[dict]:
    if not isinstance(arquivo,bytes) or not 0<len(arquivo)<=MAX_BYTES:
        raise ErroSIO('CSV ausente/excedente')
    if not isinstance(chave_hmac,bytes) or len(chave_hmac)<32:
        raise ErroSIO('chave HMAC local com 32+ bytes obrigatoria')
    if not isinstance(colunas,dict) or not CAMPOS_REQUERIDOS<=colunas.keys() or not set(colunas)<=CAMPOS_REQUERIDOS|CAMPOS_OPCIONAIS:
        raise ErroSIO('mapeamento de colunas nao homologado')
    if any(not isinstance(v,str) or not v.strip() for v in colunas.values()) or len(set(colunas.values()))!=len(colunas):
        raise ErroSIO('nomes de colunas invalidos/repetidos')
    try:
        texto=arquivo.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ErroSIO('CSV nao UTF-8: encoding requer homologacao') from exc
    if texto.lstrip().lower().startswith(('<html','<!doctype','<?xml')):
        raise ErroSIO('HTML/WAF nao equivale CSV')
    # Delimitador ponto-e-virgula explícito para locale decimal vírgula.
    reader=csv.DictReader(StringIO(texto,newline=''),delimiter=';',strict=True)
    cab=reader.fieldnames
    if not cab or len(cab)!=len(set(cab)) or not set(colunas.values())<=set(cab):
        raise ErroSIO('cabecalho nao corresponde ao CSV homologado')
    saida=[]
    ids=set()
    for i,item in enumerate(reader,start=2):
        if i>MAX_ROWS+1:
            raise ErroSIO('limite de linhas excedido')
        if None in item or any(x is None for x in item.values()):
            raise ErroSIO(f'colunas desiguais na linha {i}')
        operacao=str(item[colunas['id_operacao']]).strip()
        if not re.fullmatch(r'[A-Za-z0-9_./-]{1,100}',operacao):
            raise ErroSIO('ID de operacao ausente ou invalido')
        uid=hmac.new(chave_hmac,operacao.encode('utf-8'),'sha256').hexdigest()
        if uid in ids:
            raise ErroSIO('operacao repetida no mesmo arquivo: conciliar versoes')
        ids.add(uid)
        produto=str(item[colunas['produto']]).strip()
        if not produto or len(produto)>100:
            raise ErroSIO('produto SIO nao identificado')
        provincia=str(item[colunas['provincia_origem']]).strip() if 'provincia_origem' in colunas else ''
        moeda=str(item[colunas['moeda']]).strip() if 'moeda' in colunas else ''
        if len(provincia)>100 or len(moeda)>20:
            raise ErroSIO('provincia/moeda excessivos')
        saida.append({
            'id_hmac':uid,
            'data_concertacao':_data(item[colunas['data_concertacao']]),
            'produto':produto,
            'toneladas':_decimal(item[colunas['toneladas']]),
            'provincia_origem':provincia or None,
            'moeda':moeda or None,
            'preco_por_tonelada':_decimal(item[colunas['preco_por_tonelada']],moeda=True) if 'preco_por_tonelada' in colunas else '',
        })
    if not saida:
        raise ErroSIO('CSV sem operacoes')
    return saida


_SCHEMA="""
CREATE TABLE IF NOT EXISTS sio_edicoes (
 sha256_raw TEXT PRIMARY KEY, url_origem TEXT NOT NULL,
 inicio TEXT NOT NULL, fim TEXT NOT NULL, coletado_em TEXT NOT NULL,
 colunas_homologadas TEXT NOT NULL, quantidade INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status='QUARENTENA_OPERACOES_NAO_ENTREGA')
);
CREATE TABLE IF NOT EXISTS sio_operacoes (
 sha256_raw TEXT NOT NULL REFERENCES sio_edicoes(sha256_raw),
 id_hmac TEXT NOT NULL, data_concertacao TEXT NOT NULL,
 produto TEXT NOT NULL, toneladas TEXT NOT NULL,
 provincia_origem TEXT, moeda TEXT, preco_por_tonelada TEXT,
 natureza TEXT NOT NULL, PRIMARY KEY(sha256_raw,id_hmac)
);
CREATE INDEX IF NOT EXISTS idx_sio_data_produto ON sio_operacoes(data_concertacao,produto);
"""


def importar_exportacao_sio(*,db:sqlite3.Connection,arquivo:bytes,janela:dict,
                            colunas:dict,chave_hmac:bytes,coletado_em:datetime,
                            direitos_confirmados:bool=False,
                            layout_validado:bool=False)->dict:
    if direitos_confirmados is not True or layout_validado is not True:
        raise PermissionError('SIO exige prova de direitos e layout validado na origem')
    if not isinstance(coletado_em,datetime) or coletado_em.tzinfo is None or coletado_em.utcoffset() is None:
        raise ErroSIO('coleta deve ter timezone')
    if not isinstance(janela,dict) or janela.get('consulta_url')!=PORTAL:
        raise ErroSIO('janela nao reconhecida')
    j=planejar_periodos(janela.get('inicio'),janela.get('fim'),dias_por_janela=180)
    if len(j)!=1:
        raise ErroSIO('janela ultrapassa 180 dias')
    rows=_normalizar_csv(arquivo,colunas=colunas,chave_hmac=chave_hmac)
    if any(not janela['inicio']<=r['data_concertacao']<=janela['fim'] for r in rows):
        raise ErroSIO('data de concertacao fora da janela declarada')
    raw_hash=sha256(arquivo).hexdigest()
    ts=coletado_em.astimezone(timezone.utc).isoformat(timespec='seconds')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript(_SCHEMA)
    with db:
        old=db.execute('SELECT inicio,fim,colunas_homologadas,quantidade FROM sio_edicoes WHERE sha256_raw=?',(raw_hash,)).fetchone()
        estado=(janela['inicio'],janela['fim'],json.dumps(colunas,sort_keys=True),len(rows))
        if old is not None and tuple(old)!=estado:
            raise ErroSIO('mesmo RAW com metadados divergentes')
        if old is None:
            db.execute('INSERT INTO sio_edicoes VALUES (?,?,?,?,?,?,?,?)',
                       (raw_hash,PORTAL,janela['inicio'],janela['fim'],ts,estado[2],len(rows),
                        'QUARENTENA_OPERACOES_NAO_ENTREGA'))
            db.executemany('INSERT INTO sio_operacoes VALUES (?,?,?,?,?,?,?,?,?)',
                           [(raw_hash,r['id_hmac'],r['data_concertacao'],r['produto'],r['toneladas'],
                             r['provincia_origem'],r['moeda'],r['preco_por_tonelada'],REGISTRO) for r in rows])
    return {'source_id':'ARG_SIO_GRANOS','linhas':len(rows),'sha256_raw':raw_hash,
            'nova_edicao':old is None,'estado':'QUARENTENA_OPERACOES_NAO_ENTREGA',
            'publicacao_automatica':False,'cloud_write':False}
