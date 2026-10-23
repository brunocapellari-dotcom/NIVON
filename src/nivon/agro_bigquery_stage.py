"""Exportacao NIVON fontes agro em staging JSONL privado e verificavel.

Le SQLite LOCAL de CEPEA, IMEA, CONAB, SAGyP e SIO, sem conexao GCP
ou publicacao. SIO e exportado SOMENTE agregado, sem IDs de operacoes.
Nao agrega edicoes de um mesmo indicador para evitar duplo cômputo.
Preserva proveniencia, fonte alternativa, falta de data e versoes.
"""
from __future__ import annotations

from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

class ErroStageAgro(ValueError):
    pass


_FIELDS=('source_id','dataset_id','indicador_id','pais','produto','safra',
         'regiao','competencia','unidade','valor','data_publicacao_original',
         'coletado_utc','source_sha256','hash_natureza','classe',
         'qualidade','nivel_agregacao','status')


def _n(v):
    try:
        x=Decimal(str(v))
    except (InvalidOperation,TypeError) as e:
        raise ErroStageAgro('valor numerico invalido') from e
    if not x.is_finite() or abs(x)>Decimal('1000000000000000'):
        raise ErroStageAgro('valor fora de faixa')
    return format(x,'f')


def _utc(v):
    if not isinstance(v,str):
        raise ErroStageAgro('coleta ausente')
    try:
        dt=datetime.fromisoformat(v.replace('Z','+00:00'))
    except ValueError as exc:
        raise ErroStageAgro('coleta invalida') from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroStageAgro('coleta sem timezone')
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds')


def _r(**kw):
    kw={'status':'QUARENTENA_NAO_PUBLICAVEL',**kw}
    if set(kw)!=set(_FIELDS):
        raise ErroStageAgro('schema stage divergente')
    if kw['status']!='QUARENTENA_NAO_PUBLICAVEL':
        raise ErroStageAgro('dados nao homologados')
    if not isinstance(kw['source_sha256'],str) or len(kw['source_sha256'])!=64:
        raise ErroStageAgro('hash da fonte ausente')
    kw['coletado_utc']=_utc(kw['coletado_utc'])
    kw['valor']=_n(kw['valor'])
    return kw


def _exists(db,table):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is not None


def _argentina_sagyp(db):
    if not _exists(db,'ar_estimaciones') or not _exists(db,'ar_ediciones'):
        return
    sql="""SELECT e.*, d.sha256,d.recogido_utc,d.publicado_utc
           FROM ar_estimaciones e JOIN ar_ediciones d ON d.edicion_id=e.edicion_id
           ORDER BY e.edicion_id,e.cultivo,e.campania,e.provincia_id,e.departamento_id"""
    for d in db.execute(sql):
        for campo,indicador,unid in (
            ('superficie_sembrada_ha','AREA_PLANTADA','ha'),
            ('superficie_cosechada_ha','AREA_COLHIDA','ha'),
            ('produccion_tm','PRODUCAO','t'),
            ('rendimiento_kgxha','PRODUTIVIDADE','kg/ha'),
        ):
            if d[campo] is None:continue
            yield _r(source_id='ARG_SAGYP',dataset_id='ARG_SAGYP_ESTIMACIONES_AGRICOLAS',
                indicador_id=indicador,pais='ARG',produto=d['cultivo'],safra=d['campania'],
                regiao=f"ARG:{d['provincia_id']}:{d['departamento_id']}",
                competencia=str(d['anio']),unidade=unid,valor=d[campo],
                data_publicacao_original=d['publicado_utc'],coletado_utc=d['recogido_utc'],
                source_sha256=d['sha256'],hash_natureza='RAW',
                classe='ESTIMADO',qualidade='PUBLICACAO_NAO_VERIFICADA',
                nivel_agregacao='DEPARTAMENTO')


def _cotacoes(db):
    if not _exists(db,'cotacao_linhas') or not _exists(db,'cotacao_lotes'):
        return
    for r in db.execute("""SELECT l.*, b.fonte_solicitada,b.digest_normalizado,
                       b.primeira_coleta_utc,b.selecionada_do_cache,b.origem_declarada
                       FROM cotacao_linhas l JOIN cotacao_lotes b ON b.id=l.lote_id
                       ORDER BY b.id,l.indice"""):
        if r['valor'] is None: continue
        fonte=r['fonte_solicitada']
        qualidade='ORIGEM_ALTERNATIVA' if r['fonte_linha'] not in (fonte.lower(),) else 'DATA_PUBLICACAO_NAO_HOMOLOGADA'
        if r['selecionada_do_cache']:
            qualidade+='|CACHE'
        if r['alerta']:
            qualidade+='|'+r['alerta']
        yield _r(source_id=fonte,dataset_id=fonte+'_COTACOES',
            indicador_id=r['serie_id'],pais='BRA',produto=r['serie_id'],
            safra=r['safra'],regiao=r['localidade'],competencia=r['competencia'],
            unidade=r['unidade_original'],valor=r['valor'],
            data_publicacao_original=r['data_publicacao_local'],
            coletado_utc=r['primeira_coleta_utc'],source_sha256=r['digest_normalizado'],
            hash_natureza='NORMALIZADO_SEM_RAW',classe='INDICADOR_PUBLICADO',
            qualidade=qualidade,nivel_agregacao='COTACAO_PRACA')


def _conab(db, permitir_sintetico):
    if not _exists(db,'nivon_conab_progresso') or not _exists(db,'nivon_snapshots'):
        return
    for d in db.execute("""SELECT s.sha256,s.tipo,s.publicacao,s.source_id,c.coletado_utc,p.observacao_json
                FROM nivon_conab_progresso p JOIN nivon_snapshots s ON s.id=p.snapshot_id
                JOIN nivon_coletas c ON c.snapshot_id=s.id
                ORDER BY s.sha256,p.chave,c.coletado_utc"""):
        if d['tipo']=='SINTETICO' and not permitir_sintetico:continue
        observacao=json.loads(d['observacao_json'])
        if observacao.get('dataset_id')!='CONAB_PROGRESSO_SEMANAL':
            raise ErroStageAgro('dataset CONAB invalido')
        for campo,ind in [('pct_semana_atual','PROGRESSO_SEMANAL_ATUAL'),
                          ('pct_semana_anterior','PROGRESSO_SEMANAL_ANTERIOR'),
                          ('pct_ano_anterior','PROGRESSO_ANO_ANTERIOR'),
                          ('pct_media_5_anos','PROGRESSO_MEDIA_5_ANOS')]:
            valor=observacao.get(campo)
            if valor is None:continue
            if not 0<=Decimal(str(valor))<=1:
                raise ErroStageAgro('percentual CONAB fora do contrato')
            yield _r(source_id='CONAB',dataset_id='CONAB_PROGRESSO_SEMANAL',
                indicador_id=observacao['operacao']+'_'+ind,
                pais='BRA',produto=observacao['cultura'],safra=observacao['safra'],
                regiao=observacao['uf'],competencia=observacao['competencia'],
                unidade='fracao_0_1',valor=valor,data_publicacao_original=d['publicacao'],
                coletado_utc=d['coletado_utc'],source_sha256=d['sha256'],
                hash_natureza='RAW',
                classe='INFORMADO' if d['tipo']=='REAL_AUTORIZADO' else 'SINTETICO_TESTE',
                qualidade='PUBLICACAO_NAO_VERIFICADA|MEDIANAO_BRASIL' if observacao['uf']=='MEDIA_ESTADOS'
                     else 'PUBLICACAO_NAO_VERIFICADA',
                nivel_agregacao='UF_OU_MEDIA_ESTADOS')


def _sio(db):
    if not _exists(db,'sio_operacoes') or not _exists(db,'sio_edicoes'):
        return
    sql="""SELECT s.sha256_raw,s.coletado_em,o.data_concertacao,o.produto,o.provincia_origem,
                  o.toneladas
           FROM sio_operacoes o JOIN sio_edicoes s ON s.sha256_raw=o.sha256_raw
           ORDER BY s.sha256_raw,o.data_concertacao,o.produto,o.provincia_origem,o.id_hmac"""
    grupos={}
    for r in db.execute(sql):
        k=(r['sha256_raw'],r['coletado_em'],r['data_concertacao'],
           r['produto'],r['provincia_origem'] or 'NAO_INFORMADA')
        grupos[k]=grupos.get(k,Decimal(0))+Decimal(r['toneladas'])
    for (digest,coleta,data,produto,provincia),valor in sorted(grupos.items()):
        yield _r(source_id='ARG_SIO_GRANOS',dataset_id='ARG_SIO_OPERACOES_DECLARADAS',
            indicador_id='TONELADAS_REGISTRADAS',pais='ARG',produto=produto,safra=None,
            regiao=provincia,competencia=data,unidade='t',valor=valor,
            data_publicacao_original=None,coletado_utc=coleta,
            source_sha256=digest,hash_natureza='RAW_NAO_ARQUIVADO_AQUI',
            classe='DECLARADO_NAO_ENTREGUE',
            qualidade='LAYOUT_DECLARADO_NAO_HOMOLOGADO_INDEPENDENTEMENTE',
            nivel_agregacao='PROVINCIA_DIA_EDICAO')


def exportar_stage(*,banco:str|Path,saida:str|Path,permitir_sintetico:bool=False,
                    max_linhas:int=500_000)->dict:
    """Exporta stage atomico, sem escritas cloud e sem operacoes individuais SIO."""
    if type(permitir_sintetico) is not bool or type(max_linhas) is not int or not 1<=max_linhas<=1_000_000:
        raise ErroStageAgro('parametros invalidos')
    origem=Path(banco)
    destino=Path(saida)
    if (not origem.is_file() or origem.is_symlink() or destino.suffix!='.jsonl'
            or destino.is_symlink() or origem.resolve()==destino.resolve()):
        raise ErroStageAgro('origem ou destino invalido')
    if not destino.parent.is_dir() or destino.parent.is_symlink():
        raise ErroStageAgro('diretorio de destino deve existir e ser privado')
    mode=stat.S_IMODE(destino.parent.stat().st_mode)
    if os.name=='posix' and (mode&0o077):
        raise ErroStageAgro('diretorio de destino deve ser 0700')
    banco_uri='file:'+str(origem.resolve())+'?mode=ro'
    db=sqlite3.connect(banco_uri,uri=True,timeout=20)
    db.row_factory=sqlite3.Row
    count=0; fontes={}
    fd,tmp=tempfile.mkstemp(prefix='.nivon_stage_',suffix='.part',dir=destino.parent)
    try:
        if os.name=='posix':os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb') as out:
            h=sha256()
            for gen in (_argentina_sagyp(db),_cotacoes(db),_conab(db,permitir_sintetico),_sio(db)):
                for r in gen:
                    count+=1
                    if count>max_linhas:
                        raise ErroStageAgro('lote excedeu limite')
                    line=(json.dumps(r,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
                    out.write(line);h.update(line)
                    fontes[r['source_id']]=fontes.get(r['source_id'],0)+1
            if count==0:
                raise ErroStageAgro('nenhuma fonte elegivel no SQLite')
            out.flush();os.fsync(out.fileno())
        os.replace(tmp,str(destino))
    except BaseException:
        if os.path.exists(tmp):os.unlink(tmp)
        raise
    finally:
        db.close()
    return {'linhas':count,'por_fonte':fontes,'sha256_jsonl':h.hexdigest(),
            'status':'STAGING_PRIVADO_NAO_PUBLICAVEL',
            'google_cloud_gravado':False,'dados_reais_homologados':False}


def main():
    import argparse
    p=argparse.ArgumentParser(description='NIVON: gerar stage local JSONL sem cloud ou publicacao')
    p.add_argument('--banco',required=True)
    p.add_argument('--saida',required=True)
    p.add_argument('--max-linhas',type=int,default=500000)
    a=p.parse_args()
    resultado=exportar_stage(banco=a.banco,saida=a.saida,max_linhas=a.max_linhas)
    print(json.dumps(resultado,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
