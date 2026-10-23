"""Coletor governado CEPEA/IMEA via agrobr: API -> SQLite de quarentena.

O pacote agrobr provê o transporte. O NIVON conserva série/unidade/proveniência
e não confunde cache/fallback com nova cotação oficial. Desligado por padrão.
Dados sem publicação temporal independente NÃO entram no briefing ou backtest.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from importlib import import_module
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

FONTES={'CEPEA','IMEA'}
PRODUTOS_CEPEA={'soja','milho','boi','bezerro','trigo','algodao',
                'acucar','etanol_hidratado','etanol_anidro','cafe','arroz','leite'}
CADEIAS_IMEA={'soja','milho','algodao','bovinocultura','suinocultura','leite','conjuntura','custo_producao'}
HOSTS={'CEPEA':{'cepea.esalq.usp.br','www.cepea.esalq.usp.br','cepea.org.br','www.cepea.org.br',
                'www.noticiasagricolas.com.br','noticiasagricolas.com.br'},
       'IMEA':{'api1.imea.com.br','www.imea.com.br','imea.com.br'}}
_SCHEMA="""
CREATE TABLE IF NOT EXISTS cotacao_lotes (
 id INTEGER PRIMARY KEY, fonte_solicitada TEXT NOT NULL,
 produto_solicitado TEXT NOT NULL, digest_normalizado TEXT NOT NULL,
 fonte_url TEXT NOT NULL, primeira_coleta_utc TEXT NOT NULL,
 origem_declarada TEXT NOT NULL, selecionada_do_cache INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status='QUARENTENA_SEM_HOMOLOGACAO_TEMPORAL'),
 UNIQUE(fonte_solicitada,produto_solicitado,digest_normalizado)
);
CREATE TABLE IF NOT EXISTS cotacao_lotes_coletas (
 lote_id INTEGER NOT NULL REFERENCES cotacao_lotes(id),
 coletado_utc TEXT NOT NULL, PRIMARY KEY(lote_id,coletado_utc)
);
CREATE TABLE IF NOT EXISTS cotacao_linhas (
 lote_id INTEGER NOT NULL REFERENCES cotacao_lotes(id),
 serie_id TEXT NOT NULL, localidade TEXT NOT NULL,
 competencia TEXT, data_publicacao_local TEXT,
 safra TEXT, unidade_original TEXT,
 valor TEXT, variacao TEXT, fonte_linha TEXT NOT NULL,
 alerta TEXT, indice INTEGER NOT NULL,
 PRIMARY KEY(lote_id,indice)
);
CREATE INDEX IF NOT EXISTS idx_cotacao_serie ON cotacao_linhas(serie_id,localidade,competencia);
"""


class ErroCotacoes(ValueError):
    pass


def _data(v, *, nome):
    if v is None or str(v) in ('NaT','nan','NaN','None'):
        return None
    if isinstance(v,datetime):
        return v.isoformat()
    if isinstance(v,date):
        return v.isoformat()
    if hasattr(v,'to_pydatetime'):
        return v.to_pydatetime().isoformat()
    if isinstance(v,str):
        s=v.strip()
        try:
            datetime.fromisoformat(s.replace('Z','+00:00'))
        except ValueError as exc:
            raise ErroCotacoes(f'{nome} inválida') from exc
        return s
    # pandas.NaT ou outros nulos não são datas comprovadas.
    raise ErroCotacoes(f'{nome} não reconhecida')


def _num(v):
    if v is None or str(v) in ('NaT','nan','NaN','None'):
        return None
    if type(v) not in (int,float,Decimal,str):
        raise ErroCotacoes('numero de tipo nao permitido')
    try:
        n=Decimal(str(v))
    except (InvalidOperation,ValueError) as exc:
        raise ErroCotacoes('valor numerico invalido') from exc
    if not n.is_finite() or abs(n)>Decimal('1000000000000000'):
        raise ErroCotacoes('valor numerico nao finito/excessivo')
    return str(n)


def _url_fonte(url, fonte):
    if not isinstance(url,str):
        raise ErroCotacoes('fonte sem URL de origem comprovável')
    try:
        p=urlsplit(url)
    except ValueError as exc:
        raise ErroCotacoes('URL malformada') from exc
    if (p.scheme!='https' or p.hostname not in HOSTS[fonte]
            or p.username or p.password or p.port not in (None,443)
            or p.fragment):
        raise ErroCotacoes('URL de fonte fora da allowlist')
    return url


def _rows(frame):
    if not hasattr(frame,'to_dict'):
        raise ErroCotacoes('retorno sem DataFrame reconhecivel')
    registros=frame.to_dict(orient='records')
    if not isinstance(registros,list) or not 0<len(registros)<=25000:
        raise ErroCotacoes('tamanho de lote invalido')
    if any(not isinstance(r,dict) for r in registros):
        raise ErroCotacoes('formato de linha invalido')
    return registros


def _norm(fonte,produto,linhas):
    saida=[]
    for i,r in enumerate(linhas):
        if fonte=='CEPEA':
            for k in ('data','valor','unidade','fonte'):
                if k not in r:
                    raise ErroCotacoes('campo CEPEA faltando: '+k)
            origem=str(r['fonte']).lower()
            if origem not in {'cepea','noticias_agricolas'}:
                raise ErroCotacoes('provedor CEPEA inesperado')
            value=_num(r['valor'])
            if value is None or Decimal(value)<=0:
                raise ErroCotacoes('preco CEPEA deve ser positivo')
            competencia=_data(r['data'],nome='data cotacao')
            if not competencia:
                raise ErroCotacoes('CEPEA sem data de referencia')
            serie=f"CEPEA_{str(r.get('produto') or produto).upper()}"
            praca=str(r.get('praca') or 'NAO_DEFINIDA')
            pub=None
            safra=None
            variacao=None
            alerta='PROVEDOR_ALTERNATIVO' if origem!='cepea' else None
        else:
            for k in ('indicador_id','valor','unidade','localidade','data_publicacao'):
                if k not in r:
                    raise ErroCotacoes('campo IMEA faltando: '+k)
            identificador=str(r['indicador_id'] or '')
            if not identificador.isdigit() or len(identificador)>36:
                raise ErroCotacoes('IMEA indicador_id nao numerico')
            serie='IMEA_'+identificador
            praca=str(r.get('localidade') or 'NAO_INFORMADA')
            if len(praca)>180:
                raise ErroCotacoes('localidade muito longa')
            pub=_data(r['data_publicacao'],nome='data_publicacao')
            # data_publicacao do IMEA pode nao ter fuso; preservar hora LOCAL,
            # nao criar timestamp UTC nem assegurar instante de disponibilidade.
            competencia=pub[:10] if pub else None
            origem='imea'
            safra=str(r.get('safra') or '') or None
            value=_num(r['valor'])
            variacao=_num(r.get('variacao'))
            alerta='ZERO_COM_SIGNIFICADO_NAO_COMPROVADO' if value is not None and Decimal(value)==0 else None
            if value is None:
                alerta='VALOR_NAO_PUBLICADO' if alerta is None else alerta+'|VALOR_NAO_PUBLICADO'
            if r.get('indicador') is None:
                alerta='NOME_INDICADOR_AUSENTE' if alerta is None else alerta+'|NOME_INDICADOR_AUSENTE'
        unidade=str(r.get('unidade') or '')
        if not unidade or len(unidade)>120 or len(serie)>95:
            raise ErroCotacoes('unidade/serie invalida')
        if len(praca)>180:
            raise ErroCotacoes('praca excessiva')
        saida.append({
            'serie_id':serie,'localidade':praca,'competencia':competencia,
            'data_publicacao_local':pub,'safra':safra,
            'unidade_original':unidade,'valor':value,'variacao':variacao,
            'fonte_linha':origem,'alerta':alerta,'indice':i,
        })
    # Duplicatas exatas colapsadas, chaves repetidas com valores conflitantes
    # preservadas em edicoes separadas; nao excluir linhas nao identicas.
    keys=set()
    unique=[]
    for d in saida:
        key=tuple(d[k] for k in ('serie_id','localidade','competencia','safra','unidade_original',
                                  'valor','variacao','fonte_linha','alerta'))
        if key not in keys:
            keys.add(key)
            unique.append({**d,'indice':len(unique)})
    return unique


def armazenar_quarentena(db:sqlite3.Connection, *, fonte:str, produto:str,
                         registros:list[dict], metadata, coletado_em:datetime) -> dict:
    if fonte not in FONTES:
        raise ErroCotacoes('fonte desconhecida')
    if not isinstance(coletado_em,datetime) or coletado_em.tzinfo is None or coletado_em.utcoffset() is None:
        raise ErroCotacoes('coleta sem fuso horario')
    instante=coletado_em.astimezone(timezone.utc).isoformat(timespec='seconds')
    url=_url_fonte(getattr(metadata,'source_url',None),fonte)
    saida=_norm(fonte,produto,registros)
    digest=sha256(json.dumps(saida,sort_keys=True,ensure_ascii=False,
                             separators=(',',':')).encode('utf-8')).hexdigest()
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript(_SCHEMA)
    origem=str(getattr(metadata,'selected_source','nao_declarado') or 'nao_declarado')
    do_cache=origem.lower() in {'cache','cache_fallback'}
    with db:
        anterior=db.execute('SELECT id,fonte_url FROM cotacao_lotes WHERE fonte_solicitada=? AND produto_solicitado=? AND digest_normalizado=?',
              (fonte,produto,digest)).fetchone()
        if anterior is None:
            cur=db.execute('INSERT INTO cotacao_lotes(fonte_solicitada,produto_solicitado,digest_normalizado,fonte_url,primeira_coleta_utc,origem_declarada,selecionada_do_cache,status) VALUES (?,?,?,?,?,?,?,?)',
                (fonte,produto,digest,url,instante,origem,int(do_cache),'QUARENTENA_SEM_HOMOLOGACAO_TEMPORAL'))
            lote=cur.lastrowid
            db.executemany('''INSERT INTO cotacao_linhas
              (lote_id,serie_id,localidade,competencia,data_publicacao_local,
               safra,unidade_original,valor,variacao,fonte_linha,alerta,indice)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                [(lote,d['serie_id'],d['localidade'],d['competencia'],d['data_publicacao_local'],
                  d['safra'],d['unidade_original'],d['valor'],d['variacao'],d['fonte_linha'],
                  d['alerta'],d['indice']) for d in saida])
        else:
            lote=anterior[0]
            if anterior[1]!=url:
                raise ErroCotacoes('mesmo digest com URL de fonte alterada')
        db.execute('INSERT OR IGNORE INTO cotacao_lotes_coletas VALUES (?,?)',(lote,instante))
    return {
        'fonte':fonte,'produto':produto,'linhas':len(saida),
        'digest_dados_normalizados':digest,'nova_edicao':anterior is None,
        'cache_relatado':do_cache,'estado':'QUARENTENA_NAO_PUBLICAR',
        'prova_raw_original':False,'publicacao_temporal_independente':False,
    }


async def coletar_cotacoes(*, fonte:str, produto:str,banco:str|Path,
                          executar:bool=False,direitos_consulta:bool=False,
                          direitos_armazenamento:bool=False, api=None,
                          coletado_em:datetime|None=None) -> dict:
    """Executa uma consulta autorizada; nao segue paginas arbitrarias."""
    if executar is not True or direitos_consulta is not True or direitos_armazenamento is not True:
        raise PermissionError('coleta/armazenamento CEPEA-IMEA exigem permissoes explicitas')
    fonte=fonte.upper()
    if fonte not in FONTES or (produto not in (PRODUTOS_CEPEA if fonte=='CEPEA' else CADEIAS_IMEA)):
        raise ErroCotacoes('produto/cadeia fora da allowlist')
    if api is None:
        agrobr=import_module('agrobr')
        api=getattr(agrobr,fonte.lower())
    if fonte=='CEPEA':
        frame, meta = await api.indicador(produto,return_meta=True)
    else:
        frame, meta = await api.cotacoes(produto,return_meta=True)
    registros=_rows(frame)
    db=sqlite3.connect(str(banco),timeout=20)
    try:
        return armazenar_quarentena(db,fonte=fonte,produto=produto,
                       registros=registros,metadata=meta,
                       coletado_em=coletado_em or datetime.now(timezone.utc))
    finally:
        db.close()


def main():
    p=argparse.ArgumentParser(description='NIVON - Cotações CEPEA/IMEA autorizadas, quarentena local')
    p.add_argument('--fonte',required=True,choices=('CEPEA','IMEA'))
    p.add_argument('--produto',required=True)
    p.add_argument('--banco',required=True)
    p.add_argument('--executar',action='store_true')
    p.add_argument('--direitos-consulta',action='store_true')
    p.add_argument('--direitos-armazenamento',action='store_true')
    a=p.parse_args()
    resultado=asyncio.run(coletar_cotacoes(fonte=a.fonte,produto=a.produto,banco=a.banco,
                        executar=a.executar,direitos_consulta=a.direitos_consulta,
                        direitos_armazenamento=a.direitos_armazenamento))
    print(json.dumps(resultado,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
