"""Consolida bases SQLite independentes do NIVON em lotes BigQuery.

Nao acessa rede nem GCP. Cada colecao entra pelo exportador governado
existente, preservando vintages/hashes e suprimindo duplicatas exatas.
Lotes sao privados, atomicos por execucao e compatíveis com loader offline.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from .agro_bigquery_stage import _FIELDS, ErroStageAgro, exportar_stage
from .agro_bigquery_loader import validar_lote, ErroUploadAgro


class ErroConsolidacao(ValueError):
    pass


def _diretorio_privado(diretorio):
    d=Path(diretorio)
    if not d.is_dir() or d.is_symlink():
        raise ErroConsolidacao('diretorio de saida deve existir e ser real')
    if os.name=='posix' and (stat.S_IMODE(d.stat().st_mode)&0o077):
        raise ErroConsolidacao('diretorio de saida deve ser privado 0700')
    return d


def _canonico(linha:bytes)->tuple[bytes,dict]:
    try:
        row=json.loads(linha.decode('utf-8'))
    except (UnicodeError,ValueError) as exc:
        raise ErroConsolidacao('linha JSONL de fonte invalida') from exc
    if not isinstance(row,dict) or set(row)!=set(_FIELDS):
        raise ErroConsolidacao('schema de fonte alterado')
    if row.get('status')!='QUARENTENA_NAO_PUBLICAVEL':
        raise ErroConsolidacao('dado de fonte nao esta em quarentena')
    if 'id_hmac' in row or 'id_operacao' in row:
        raise ErroConsolidacao('identificadores individuais SIO nao permitidos')
    return (json.dumps(row,sort_keys=True,ensure_ascii=False,
                       separators=(',',':'))+'\n').encode('utf-8'),row


def consolidar_sqlites(*,bancos:list[str|Path],pasta_saida:str|Path,
                      prefixo:str='agro',max_linhas_por_lote:int=25000,
                      max_bytes_por_lote:int=30_000_000)->dict:
    """Cria N JSONL + manifesto. Nao altera SQLite, nao envia GCP."""
    if (not isinstance(bancos,list) or not bancos or len(bancos)>30):
        raise ErroConsolidacao('fornecer 1 a 30 bancos SQLite')
    if (type(max_linhas_por_lote) is not int or not 1<=max_linhas_por_lote<=100_000
        or type(max_bytes_por_lote) is not int or not 4096<=max_bytes_por_lote<=90_000_000):
        raise ErroConsolidacao('limites de lote invalidos')
    if not isinstance(prefixo,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{1,32}',prefixo):
        raise ErroConsolidacao('prefixo invalido')
    root=_diretorio_privado(pasta_saida)
    names=[]
    for banco in bancos:
        caminho=Path(banco)
        if not caminho.is_file() or caminho.is_symlink():
            raise ErroConsolidacao('banco SQLite nao acessivel')
        names.append(str(caminho.resolve()))
    if len(set(names))!=len(names):
        raise ErroConsolidacao('mesmo banco incluído duas vezes')
    names.sort()
    manifest_nome=prefixo+'-manifesto.json'
    if (root/manifest_nome).exists() or list(root.glob(prefixo+'-lote-*.jsonl')):
        raise ErroConsolidacao('saida preexistente, nao sobrescrever lote anterior')

    with tempfile.TemporaryDirectory(prefix='.nivon-consolidar-',dir=root) as temp:
        tempdir=Path(temp)
        dedupe=set()
        chaves={}
        linhas=[]
        fontes=Counter()
        por_banco=[]
        for n,banco in enumerate(names):
            tmp=tempdir/('fonte-'+str(n)+'.jsonl')
            try:
                meta=exportar_stage(banco=banco,saida=tmp,max_linhas=500_000)
            except (ErroStageAgro,ValueError) as exc:
                raise ErroConsolidacao('banco sem dados exportaveis ou fora do contrato') from exc
            por_banco.append({'banco_sha256_caminho':sha256(banco.encode()).hexdigest(),
                              'linhas_origem':meta['linhas'],
                              'sha256_jsonl_fonte':meta['sha256_jsonl']})
            with tmp.open('rb') as data:
                for raw in data:
                    canon,row=_canonico(raw)
                    if len(canon)>4096:
                        raise ErroConsolidacao('linha excede maximo do loader')
                    digest=sha256(canon).hexdigest()
                    if digest in dedupe:
                        continue
                    dedupe.add(digest)
                    chave=tuple(row.get(k) for k in (
                        'dataset_id','indicador_id','pais','produto','safra',
                        'regiao','competencia','unidade','coletado_utc',
                        'source_sha256','hash_natureza','nivel_agregacao'))
                    anterior=chaves.get(chave)
                    if anterior is not None and anterior != row['valor']:
                        raise ErroConsolidacao('mesma vintage/chave contem valores distintos')
                    chaves[chave]=row['valor']
                    linhas.append((canon,row['source_id']))
            tmp.unlink()
        if not linhas:
            raise ErroConsolidacao('nenhuma linha de dados')
        linhas.sort(key=lambda x:x[0])
        lotes=[]
        atual=[]
        bytes_lote=0
        for raw,fonte in linhas:
            if atual and (len(atual)>=max_linhas_por_lote or bytes_lote+len(raw)>max_bytes_por_lote):
                lotes.append(atual)
                atual=[];bytes_lote=0
            if len(raw)>max_bytes_por_lote:
                raise ErroConsolidacao('linha excede limite de bytes')
            atual.append(raw)
            bytes_lote+=len(raw)
            fontes[fonte]+=1
        if atual:lotes.append(atual)
        arquivos=[]
        for i,registros in enumerate(lotes,start=1):
            nome=f'{prefixo}-lote-{i:04}.jsonl'
            path=tempdir/nome
            content=b''.join(registros)
            path.write_bytes(content)
            if os.name=='posix':path.chmod(0o600)
            info=validar_lote(path)
            arquivos.append({
                'arquivo':nome,'linhas':info['linhas'],
                'bytes':info['bytes'],'sha256_jsonl':info['sha256_jsonl'],
                'fontes':info['fontes']
            })
        manifesto={'schema':'NIVON_AGRO_CONSOLIDADO_V1',
                   'estado':'LOTES_PRIVADOS_NAO_PUBLICAVEIS',
                   'bancos_entrada':por_banco,
                   'linhas_distintas':len(linhas),
                   'linhas_duplicadas_descartadas':sum(x['linhas_origem'] for x in por_banco)-len(linhas),
                   'por_fonte':dict(sorted(fontes.items())),
                   'lotes':arquivos,'cloud_write':False}
        mtmp=tempdir/manifest_nome
        mtmp.write_text(json.dumps(manifesto,indent=2,ensure_ascii=False,
                                  sort_keys=True)+'\n',encoding='utf-8')
        if os.name=='posix':mtmp.chmod(0o600)
        # Vinculos atomicos sem substituir destino preexistente; rollback
        # se o commit nao conseguir publicar todos os arquivos.
        publicados=[]
        try:
            for nome in [x['arquivo'] for x in arquivos]+[manifest_nome]:
                os.link(tempdir/nome,root/nome)
                publicados.append(root/nome)
        except BaseException:
            for path in publicados:path.unlink(missing_ok=True)
            raise
        return {**manifesto,'manifesto':str(root/manifest_nome)}


def main():
    p=argparse.ArgumentParser(description='NIVON consolidar bases locais em JSONL BigQuery sem GCP')
    p.add_argument('--banco',action='append',required=True,
                   help='repetir para cada SQLite privado')
    p.add_argument('--pasta-saida',required=True)
    p.add_argument('--prefixo',default='agro')
    p.add_argument('--max-linhas-por-lote',type=int,default=25000)
    args=p.parse_args()
    result=consolidar_sqlites(bancos=args.banco,pasta_saida=args.pasta_saida,
             prefixo=args.prefixo,max_linhas_por_lote=args.max_linhas_por_lote)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
