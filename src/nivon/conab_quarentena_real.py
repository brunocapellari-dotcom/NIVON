"""Persistência de XLSX REAL da CONAB exclusivamente em quarentena local.

Recebe apenas pacotes gerados por captura supervisionada (RAW+manifesto).
Confere novamente o pacote, reproduz o parser OOXML oficial do NIVON,
preserva edições/vintages em SQLite e nunca promove dados aos motores
editoriais ou ao BigQuery sem governança separada.
"""
from __future__ import annotations

from datetime import datetime,timezone
from hashlib import sha256
import json
import sqlite3
from pathlib import Path
import re

from .auditoria_publicacao_conab import validar_publicacao_conab
from .captura_xlsx_conab import (
    RAW_FILE,EVIDENCE_FILE,verificar_pacote_captura_local
)
from .conab_replay_xlsx import reexecutar_xlsx_conab,PARSER_ID
from .conab_resolver_anexo import montar_registro_captura

_SCHEMA="""
CREATE TABLE IF NOT EXISTS conab_real_edicoes_quarentena (
 id_edicao TEXT NOT NULL,
 sha256_raw TEXT NOT NULL,
 pagina_url TEXT NOT NULL,
 url_anexo TEXT NOT NULL,
 publicacao_data TEXT NOT NULL,
 competencia TEXT NOT NULL,
 coletado_utc TEXT NOT NULL,
 quantidade_observacoes INTEGER NOT NULL,
 parser_id TEXT NOT NULL,
 estado TEXT NOT NULL CHECK(estado='QUARENTENA_DADO_REAL_NAO_HOMOLOGADO'),
 PRIMARY KEY(id_edicao,sha256_raw)
);
CREATE TABLE IF NOT EXISTS conab_real_observacoes_quarentena (
 id_edicao TEXT NOT NULL,
 sha256_raw TEXT NOT NULL,
 chave_semantica TEXT NOT NULL,
 registro_json TEXT NOT NULL,
 PRIMARY KEY(id_edicao,sha256_raw,chave_semantica),
 FOREIGN KEY(id_edicao,sha256_raw)
  REFERENCES conab_real_edicoes_quarentena(id_edicao,sha256_raw)
);
CREATE INDEX IF NOT EXISTS idx_conab_real_quarentena_periodo
 ON conab_real_edicoes_quarentena(competencia,id_edicao);
"""


class ErroQuarentenaConab(ValueError):
    pass


def importar_pacote_real(*,db:sqlite3.Connection,registro:dict,pasta:str|Path,
                        executar:bool=False,direitos_armazenamento:bool=False,
                        verificar=verificar_pacote_captura_local,
                        parser=reexecutar_xlsx_conab)->dict:
    if executar is not True or direitos_armazenamento is not True:
        raise PermissionError('importacao real CONAB exige direitos e opt-in')
    meta=validar_publicacao_conab(registro)
    resultado=verificar(registro,pasta)
    if (not isinstance(resultado,dict) or resultado.get('publicacao_permitida') is not False
            or resultado.get('migracao_permitida') is not False
            or not re.fullmatch('[a-f0-9]{64}',str(resultado.get('sha256','')))):
        raise ErroQuarentenaConab('verificacao do pacote nao comprovada')
    root=Path(pasta)
    raw=(root/RAW_FILE).read_bytes()
    digest=sha256(raw).hexdigest()
    if resultado['sha256']!=digest:
        raise ErroQuarentenaConab('hash do RAW nao confirma manifesto')
    doc=json.loads((root/EVIDENCE_FILE).read_text(encoding='utf-8'))
    coleta=doc['transport_evidencia']['finalizado_utc']
    ts=datetime.fromisoformat(coleta.replace('Z','+00:00'))
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ErroQuarentenaConab('coleta sem timezone')
    ts=ts.astimezone(timezone.utc).isoformat(timespec='seconds')
    parsed=parser(raw,sha256_origem=digest,
                  url_origem=meta['url_anexo'],coletado_em=ts,publicado_em=None)
    if (parsed.get('raw_sha256')!=digest or parsed.get('parser_id')!=PARSER_ID
            or not isinstance(parsed.get('mapa_semantico'),dict)
            or len(parsed['mapa_semantico'])!=resultado['observacoes']):
        raise ErroQuarentenaConab('parser/hashes divergentes do pacote verificado')
    dados=[]
    for chave,linha in sorted(parsed['mapa_semantico'].items(),key=lambda x:str(x[0])):
        if not isinstance(linha,str):
            raise ErroQuarentenaConab('observacao serializada invalida')
        try:val=json.loads(linha)
        except ValueError as exc:
            raise ErroQuarentenaConab('json do parser invalido') from exc
        if not isinstance(val,dict) or val.get('source_url')!=meta['url_anexo']:
            raise ErroQuarentenaConab('origem da observacao divergente')
        dados.append((meta['id_edicao'],digest,sha256(str(chave).encode('utf-8')).hexdigest(),linha))
    if not dados:
        raise ErroQuarentenaConab('planilha sem observacoes')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript(_SCHEMA)
    with db:
        anterior=db.execute('''SELECT quantidade_observacoes,parser_id
              FROM conab_real_edicoes_quarentena WHERE id_edicao=? AND sha256_raw=?''',
              (meta['id_edicao'],digest)).fetchone()
        if anterior is not None:
            if tuple(anterior)!=(len(dados),PARSER_ID):
                raise ErroQuarentenaConab('mesma versao divergente')
        else:
            db.execute('INSERT INTO conab_real_edicoes_quarentena VALUES (?,?,?,?,?,?,?,?,?,?)',
                (meta['id_edicao'],digest,meta['url_pagina'],meta['url_anexo'],
                 meta['pagina_publicada_data'],meta['semana_planilha'],ts,len(dados),
                 PARSER_ID,'QUARENTENA_DADO_REAL_NAO_HOMOLOGADO'))
            db.executemany('INSERT INTO conab_real_observacoes_quarentena VALUES (?,?,?,?)',dados)
    return {'id_edicao':meta['id_edicao'],'raw_sha256':digest,
            'observacoes':len(dados),'nova_versao':anterior is None,
            'status':'QUARENTENA_DADO_REAL_NAO_HOMOLOGADO',
            'publicacao_permitida':False,'google_cloud_gravado':False}


def importar_pacotes_locais(*,banco:str|Path,raiz:str|Path,
                           executar:bool=False,direitos_armazenamento:bool=False)->dict:
    """Consome pacotes da execução CONAB anterior sem qualquer HTTP."""
    if executar is not True or direitos_armazenamento is not True:
        raise PermissionError('importacao de pacotes exige autorizacao explicita')
    raiz=Path(raiz)
    if not raiz.is_dir() or raiz.is_symlink():
        raise ErroQuarentenaConab('raiz de pacotes nao e diretorio real')
    import os,stat
    if os.name=='posix' and stat.S_IMODE(raiz.stat().st_mode)&0o077:
        raise ErroQuarentenaConab('raiz nao privada')
    db=sqlite3.connect(str(banco),timeout=20)
    try:
        db.row_factory=sqlite3.Row
        rows=db.execute('''SELECT s.pagina_url,s.periodo_rotulo,s.titulo,
                        a.url_documento,a.url_anexo,a.pagina_publicada_data,
                        a.hash_html_documento,a.primeira_coleta_utc
                        FROM conab_anexos_resolvidos a
                        JOIN conab_semanas_descobertas s ON s.pagina_url=a.pagina_semana
                        ORDER BY s.pagina_url,a.url_documento''').fetchall()
        feitos=[]
        for linha in rows:
            page=linha['pagina_url']
            origem={
                'pagina_oficial':page,'titulo':linha['titulo'],
                'periodo_rotulo':linha['periodo_rotulo']
            }
            resolucao={'pagina_semana':page,'url_documento':linha['url_documento'],
                       'url_anexo':linha['url_anexo'],
                       'publicacao_data':linha['pagina_publicada_data'],
                       'hash_html_documento':linha['hash_html_documento'],
                       'coletado_em_utc':linha['primeira_coleta_utc'],
                       'estado':'LINK_XLSX_DESCOBERTO_NAO_BAIXADO'}
            reg=montar_registro_captura(indice_semana=origem,resolucao=resolucao)
            h=sha256(resolucao['url_anexo'].encode('utf-8')).hexdigest()[:16]
            folder=raiz/(reg['id_edicao']+'_'+h)
            if not folder.is_dir():
                continue  # link sem pacote baixado nao implica falha da fonte
            feitos.append(importar_pacote_real(
                db=db,registro=reg,pasta=folder,
                executar=True,direitos_armazenamento=True))
        return {'arquivos_importados':len(feitos),'observacoes_processadas':
                sum(x['observacoes'] for x in feitos),
                'versoes_novas':sum(x['nova_versao'] for x in feitos),
                'pacotes':feitos,'publicacao_permitida':False,
                'status':'QUARENTENA_LOCAL_SEM_GO_LIVE'}
    finally:
        db.close()


def main():
    import argparse
    p=argparse.ArgumentParser(description='Importar pacotes reais CONAB autorizados em SQLite de quarentena')
    p.add_argument('--banco',required=True)
    p.add_argument('--raiz',required=True)
    p.add_argument('--executar',action='store_true')
    p.add_argument('--direitos-armazenamento',action='store_true')
    args=p.parse_args()
    print(json.dumps(importar_pacotes_locais(
        banco=args.banco,raiz=args.raiz,executar=args.executar,
        direitos_armazenamento=args.direitos_armazenamento),
        ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
