"""Quadro operacional de prontidao CEPEA/IMEA/CONAB/Argentina do NIVON.

Audita somente metadados locais de bancos SQLite e o catalogo mestre.
Nunca abre rede, baixa dados, verifica pagamentos ou muda status do
catalogo. Presenca de linhas nao comprova fonte oficial nem atualidade.
"""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
from pathlib import Path
import argparse
import json
import sqlite3

from .catalogo_fontes import carregar_catalogo
from .rotas_coleta import carregar_rotas,validar_rotas


FONTES_AVALIADAS={
    'CEPEA_FISICO':('cotacao_lotes',"fonte_solicitada='CEPEA'"),
    'IMEA_FISICO':('cotacao_lotes',"fonte_solicitada='IMEA'"),
    'CONAB_PROGRESSO_SEMANAL':('conab_real_edicoes_quarentena','1=1'),
    'ARG_SAGYP_ESTIMACIONES_AGRICOLAS':('ar_ediciones','1=1'),
    'ARG_SIO_OPERACOES_DECLARADAS':('sio_edicoes','1=1'),
    'ARG_DJVE_DECLARACOES_EXPORTACAO':(None,None),
    'ARG_MAGYP_COMPRAS_GRANOS':(None,None),
}
CAMPOS_COLETA={
    'cotacao_lotes':'primeira_coleta_utc',
    'nivon_snapshots':None,
    'conab_real_edicoes_quarentena':'coletado_utc',
    'ar_ediciones':'recogido_utc',
    'sio_edicoes':'coletado_em',
}
_LIMITES_DIAS={
    'HOURLY':1,'SIX_HOURLY':1,'TWICE_DAILY':1,
    'DAILY':3,'INTRADAY':2,'WEEKLY':10,
    'BIWEEKLY':21,'MONTHLY':45,'QUARTERLY':110,
    'SEASONAL':210,'IRREGULAR':None
}


class ErroPainelAgro(ValueError):
    pass


def _tabelas(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _datetime_utc(s):
    if not isinstance(s,str):return None
    try:
        v=datetime.fromisoformat(s.replace('Z','+00:00'))
    except ValueError:
        return None
    if v.tzinfo is None or v.utcoffset() is None:return None
    return v.astimezone(timezone.utc)


def _inspecionar(db,table,where):
    if (table=='conab_real_edicoes_quarentena'
            and table not in _tabelas(db)
            and 'nivon_snapshots' in _tabelas(db)):
        # Legado de snapshots sinteticos, nao equivalem a RAW real.
        table='nivon_snapshots'
        where="dataset_id='CONAB_PROGRESSO_SEMANAL'"
    if table not in _tabelas(db):
        return 0,None
    col={r[1] for r in db.execute('PRAGMA table_info('+table+')')}
    timestamp=CAMPOS_COLETA[table]
    if timestamp is None:
        # Para CONAB o timestamp estah na relacao de coletas, e nao no
        # snapshot. Usar MAX da tabela de coletas da mesma edicao.
        if 'nivon_coletas' not in _tabelas(db):
            return 0,None
        q="""SELECT COUNT(DISTINCT s.id), MAX(c.coletado_utc)
             FROM nivon_snapshots s
             LEFT JOIN nivon_coletas c ON c.snapshot_id=s.id
             WHERE s.dataset_id='CONAB_PROGRESSO_SEMANAL'"""
    else:
        if timestamp not in col:return 0,None
        # Identificador de tabela vem de mapeamento estatico, nao do usuario.
        q=f'SELECT COUNT(*),MAX({timestamp}) FROM {table} WHERE {where}'
    try:
        n,ts=db.execute(q).fetchone()
    except sqlite3.DatabaseError:
        return 0,None
    return int(n or 0),_datetime_utc(ts)


def auditar_fontes_agro(*,bancos:list[str|Path],agora:datetime|None=None,
                       catalogo=None,rotas=None)->dict:
    """Resumo de evidencias locais, sem certificacao de go-live."""
    if not isinstance(bancos,list) or len(bancos)>30:
        raise ErroPainelAgro('bancos deve ser lista de no maximo 30 paths')
    agora=agora or datetime.now(timezone.utc)
    if not isinstance(agora,datetime) or agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroPainelAgro('agora precisa de timezone')
    agora=agora.astimezone(timezone.utc)
    cat=catalogo or carregar_catalogo()
    route=rotas or carregar_rotas()
    validar_rotas(route,cat)
    dmap={x['id']:x for x in cat['datasets']}
    rmap={x['dataset_id']:x for x in route['entries']}
    dbs=[]
    caminhos=[]
    try:
        for p in bancos:
            arq=Path(p)
            if not arq.is_file() or arq.is_symlink():
                raise ErroPainelAgro('banco de dados local ausente ou simbolico')
            path=str(arq.resolve())
            if path in caminhos:
                raise ErroPainelAgro('banco repetido')
            caminhos.append(path)
            db=sqlite3.connect('file:'+path+'?mode=ro',uri=True,timeout=5)
            dbs.append(db)
        saida=[]
        for id_,(table,where) in FONTES_AVALIADAS.items():
            d=dmap.get(id_)
            r=rmap.get(id_)
            if d is None or r is None:
                raise ErroPainelAgro('fonte prioritaria ausente do catalogo '+id_)
            volumes=[]
            tempos=[]
            for db in dbs:
                if table is None:continue
                qtd,ultimo=_inspecionar(db,table,where)
                volumes.append(qtd)
                if ultimo:tempos.append(ultimo)
            total=sum(volumes)
            maior=max(tempos) if tempos else None
            limite=_LIMITES_DIAS.get(d['cadence'])
            atraso=None
            if maior is not None:
                atraso=round((agora-maior).total_seconds()/86400,2)
            # "frescor" indica somente coleta do banco, nunca o tempo de
            # validade/publicacao do dado da fonte.
            estagnado=(atraso>limite if atraso is not None and limite is not None else None)
            if table is None:estado='ADAPTADOR_REAL_AINDA_NAO_IMPLEMENTADO'
            elif total==0:estado='SEM_EDICOES_LOCAIS_COMPROVADAS'
            else:estado='EDICOES_PRESENTES_NAO_HOMOLOGADAS'
            if atraso is not None and atraso<-(5/1440):
                estado='DATA_COLETA_FUTURA_INVALIDA'
            saida.append({
                'dataset_id':id_,'prioridade':d['priority'],
                'cadencia_declarada':d['cadence'],
                'edicoes_locais_contadas':total,
                'ultima_coleta_local_utc':maior.isoformat() if maior else None,
                'dias_desde_ultima_coleta_local':atraso,
                'coleta_local_em_atraso':estagnado,
                'estado':estado,
                'codigo_declarado':d['existing_module'],
                'coleta_ativada':False,'go_live_confirmado':False,
                'bloqueios':r['gates_missing'],
                'proxima_acao':(
                    'IMPLEMENTAR_PARSER_DE_FONTE_OFICIAL' if table is None else
                    'HOMOLOGAR_COLETA_REAL_CADENCIA_E_DIREITOS' if total else
                    'OBTER_EDICAO_REAL_COM_RAW_HASH_E_DATA'
                ),
            })
        return {
            'gerado_utc':agora.isoformat(timespec='seconds'),
            'status':'DIAGNOSTICO_SEM_AUTORIZACAO_DE_COLETA',
            'fontes':saida,'total_edicoes_locais':sum(x['edicoes_locais_contadas'] for x in saida),
            'fontes_homologadas_em_producao':0,
            'cloud_confirmado':False
        }
    finally:
        for db in dbs:db.close()


def main():
    ap=argparse.ArgumentParser(description='NIVON: situacao local das fontes agro, sem rede')
    ap.add_argument('--banco',action='append',default=[])
    args=ap.parse_args()
    out=auditar_fontes_agro(bancos=args.banco)
    print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=='__main__':
    main()
