"""Comex Stat MDIC: processamento LOCAL incremental em memória limitada.

Importa arquivos anuais já disponibilizados por meio autorizado, sem HTTP.
Quatro contratos: EXP/IMP por NCM e EXP/IMP municipal fiscal SH4.
Agregados por chaves explícitas; totais de controle abrangem TODAS as linhas,
inclusive posições fora do filtro. Não são reconciliação oficial ou frete.
"""
from __future__ import annotations
import csv
import hashlib
import io
import os
from contextlib import contextmanager
import re
import stat
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .mdic_exportacao import HEADER as EXP_HEADER
from .mdic_importacao import COLUNAS as IMP_HEADER
from .mdic_municipios import CABECALHO as MUN_HEADER

class ErroStreamMDIC(ValueError):
    pass


class _BytesComHash(io.RawIOBase):
    """Só computa SHA dos bytes entregues ao próprio parser CSV."""
    def __init__(self, file):
        self.file=file
        self.sha=hashlib.sha256()
        self.quantidade=0
    def readable(self):
        return True
    def readinto(self, buffer):
        n=self.file.readinto(buffer)
        if n:
            self.sha.update(memoryview(buffer)[:n])
            self.quantidade+=n
        return n
    def close(self):
        if not self.closed:
            self.file.close()
        super().close()

@contextmanager
def _abrir_csv_com_hash(caminho:Path, metadata):
    """Uma única leitura; sem seguir symlink entre verificação e abertura."""
    fd=os.open(caminho,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|
               getattr(os,"O_NONBLOCK",0))
    with os.fdopen(fd,"rb",buffering=0) as original:
        atual=os.fstat(original.fileno())
        if (not stat.S_ISREG(atual.st_mode)
            or (atual.st_dev,atual.st_ino,atual.st_size,atual.st_mtime_ns,
                atual.st_ctime_ns)!=(metadata.st_dev,metadata.st_ino,
                                   metadata.st_size,metadata.st_mtime_ns,
                                   metadata.st_ctime_ns)):
            raise ErroStreamMDIC("arquivo trocado antes do parser")
        leitor=_BytesComHash(original)
        with io.TextIOWrapper(io.BufferedReader(leitor,buffer_size=262144),
                encoding="utf-8-sig",errors="strict",newline="") as texto:
            yield texto,leitor,original

_MODO={
    ("EXPORTACAO","NCM"):("EXP", EXP_HEADER),
    ("IMPORTACAO","NCM"):("IMP", IMP_HEADER),
    ("EXPORTACAO","MUNICIPIO_SH4"):("EXP", MUN_HEADER),
    ("IMPORTACAO","MUNICIPIO_SH4"):("IMP", MUN_HEADER),
}

def _inteiro(txt, *, campo, limite=10**18):
    if not isinstance(txt,str) or not re.fullmatch(r"\d+",txt.strip()):
        raise ErroStreamMDIC(f"{campo}: inteiro não negativo obrigatório")
    val=int(txt.strip())
    if val>limite: raise ErroStreamMDIC(f"{campo}: acima do limite técnico")
    return val

def _utc(coleta):
    if not isinstance(coleta,str):raise ErroStreamMDIC("coleta ISO obrigatória")
    try: dt=datetime.fromisoformat(coleta.replace("Z","+00:00"))
    except ValueError as exc:raise ErroStreamMDIC("coleta ISO inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:raise ErroStreamMDIC("coleta sem timezone")
    return dt.astimezone(timezone.utc).isoformat()

def processar_arquivo_anual(caminho: str | Path, *, ano: int, direcao: str,
                            granularidade: str, codigos: frozenset[str],
                            coletado_em: str, limite_bytes: int=1_500_000_000,
                            limite_linhas: int=25_000_000,
                            limite_chaves: int=100_000)->dict:
    """Retorna mensal e recortes filtrados (não retorna linhas/PII).

    SHA calculado nos EXATOS bytes consumidos pelo leitor CSV, em uma única
    passagem. Validar também identidade (inode) e alteração durante leitura.
    """
    if (direcao,granularidade) not in _MODO:raise ErroStreamMDIC("modalidade inválida")
    if type(ano) is not int or not 1997<=ano<=2100:
        raise ErroStreamMDIC("ano inválido")
    if type(limite_bytes) is not int or not 0<limite_bytes<=2_000_000_000:
        raise ErroStreamMDIC("limite_bytes inválido")
    if type(limite_linhas) is not int or not 0<limite_linhas<=30_000_000:
        raise ErroStreamMDIC("limite_linhas inválido")
    if type(limite_chaves) is not int or not 0<limite_chaves<=300_000:
        raise ErroStreamMDIC("limite_chaves inválido")
    digits=8 if granularidade=="NCM" else 4
    if (not isinstance(codigos,frozenset) or not codigos or len(codigos)>3000
        or any(not isinstance(x,str) or not re.fullmatch(rf"\d{{{digits}}}",x) for x in codigos)):
        raise ErroStreamMDIC("códigos devem ser lista explícita NCM8/SH4, não inferida")
    coleta=_utc(coletado_em)
    prefix,header=_MODO[(direcao,granularidade)]
    nome=f"{prefix}_{ano}"+("_MUN" if granularidade=="MUNICIPIO_SH4" else "")+".csv"
    p=Path(caminho)
    if p.name!=nome or p.suffix.lower()!=".csv" or p.is_symlink() or not p.is_file():
        raise ErroStreamMDIC("nome/arquivo anual incompatível com contrato MDIC")
    info=p.stat()
    if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=limite_bytes:
        raise ErroStreamMDIC("arquivo não regular, vazio ou fora do limite")
    # Uma passagem única; sem janela entre hashing e parsing.
    chaves=defaultdict(lambda:[0,0,0,0,0])
    meses=defaultdict(lambda:[0,0,0,0])
    total=filtradas=0
    with _abrir_csv_com_hash(p,info) as (stream,medidor,arquivo_binario):
        leitor=csv.DictReader(stream,delimiter=";")
        if tuple(leitor.fieldnames or ())!=header:
            raise ErroStreamMDIC("schema diverge do arquivo anual oficial")
        for row in leitor:
            total+=1
            if total>limite_linhas:raise ErroStreamMDIC("limite_linhas excedido")
            if None in row or any(row.get(k) is None for k in header):
                raise ErroStreamMDIC("registro desalinhado")
            if _inteiro(row["CO_ANO"],campo="CO_ANO")!=ano:
                raise ErroStreamMDIC("ano dentro do arquivo difere do nome")
            mes=_inteiro(row["CO_MES"],campo="CO_MES")
            if not 1<=mes<=12:raise ErroStreamMDIC("mês inválido")
            produto=(row["CO_NCM"] if granularidade=="NCM" else row["SH4"]).strip()
            if not re.fullmatch(rf"\d{{{digits}}}",produto):
                raise ErroStreamMDIC("produto com código NCM/SH4 inválido")
            uf_key="SG_UF_NCM" if granularidade=="NCM" else "SG_UF_MUN"
            uf=row[uf_key].strip()
            if not re.fullmatch(r"[A-Z]{2}",uf):
                raise ErroStreamMDIC("UF inválida")
            pais=row["CO_PAIS"].strip()
            if not re.fullmatch(r"\d{1,3}",pais):raise ErroStreamMDIC("código do país inválido")
            kg=_inteiro(row["KG_LIQUIDO"],campo="KG_LIQUIDO")
            usd=_inteiro(row["VL_FOB"],campo="VL_FOB")
            frete=seguro=0
            if granularidade=="NCM":
                for campo in ("CO_UNID","QT_ESTAT","CO_VIA","CO_URF"):
                    _inteiro(row[campo],campo=campo)
                via=row["CO_VIA"].strip()
                urf=row["CO_URF"].strip()
                if direcao=="IMPORTACAO":
                    frete=_inteiro(row["VL_FRETE"],campo="VL_FRETE")
                    seguro=_inteiro(row["VL_SEGURO"],campo="VL_SEGURO")
                chave=(mes,produto,uf,pais,via,urf)
            else:
                cod_mun=row["CO_MUN"].strip()
                if not re.fullmatch(r"\d{1,7}",cod_mun):
                    raise ErroStreamMDIC("município fiscal inválido")
                chave=(mes,produto,uf,pais,cod_mun)
            m=meses[mes];m[0]+=kg;m[1]+=usd;m[2]+=1;m[3]+=frete+seguro
            if produto not in codigos:continue
            if chave not in chaves and len(chaves)>=limite_chaves:
                raise ErroStreamMDIC("limite de chaves agregadas excedido")
            c=chaves[chave]
            c[0]+=kg;c[1]+=usd;c[2]+=frete;c[3]+=seguro;c[4]+=1
            filtradas+=1
        lidos=medidor.quantidade
        digest=medidor.sha.hexdigest()
        fd_final=os.fstat(arquivo_binario.fileno())
    final=p.stat()
    assinatura=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
    if (assinatura(fd_final)!=assinatura(info)
            or assinatura(final)!=assinatura(info)
            or lidos!=info.st_size):
        raise ErroStreamMDIC("arquivo alterado durante leitura, snapshot inconsistente")
    if not total or not filtradas:
        raise ErroStreamMDIC("nenhuma linha selecionada: ausência não representa zero")
    recortes=[]
    for chave,(kg,usd,frete,seguro,n) in sorted(chaves.items()):
        mes,produto,uf,pais=chave[:4]
        row={"competencia":f"{ano:04d}-{mes:02d}",
             "classificacao":granularidade,"codigo_produto":produto,"uf":uf,
             "pais":pais,"peso_liquido_kg":kg,"valor_fob_usd":usd,
             "frete_internacional_usd":frete if direcao=="IMPORTACAO" and granularidade=="NCM" else None,
             "seguro_internacional_usd":seguro if direcao=="IMPORTACAO" and granularidade=="NCM" else None,
             "linhas_agrupadas":n}
        if granularidade=="NCM":
            row.update({"via":chave[4],"urf":chave[5],
                        "uf_nao_prova_municipio":True})
        else:
            row.update({"codigo_municipio_fiscal":chave[4],
                        "codigo_ibge_nao_validado":True,
                        "nao_origem_fisica":True})
        recortes.append(row)
    return {"dataset_id":"MDIC_COMEX_NCM" if granularidade=="NCM" else "MDIC_COMEX_MUNICIPIO_SH4",
            "direcao":direcao,"granularidade":granularidade,"ano":ano,
            "sha256_original":digest,"bytes_original":lidos,
            "coletado_em":coleta,"publicado_em":None,
            "linhas_total":total,"linhas_filtradas":filtradas,
            "totais_arquivo_por_mes":[{"competencia":f"{ano}-{mes:02d}",
                      "kg":v[0],"fob_usd":v[1],"linhas":v[2],
                      "frete_seguro_internacional_usd":v[3] if direcao=="IMPORTACAO" and granularidade=="NCM" else None}
                     for mes,v in sorted(meses.items())],
            "recortes":recortes,"verificacao_totais_oficiais":False,
            "situacao":"ARQUIVO_LOCAL_NAO_HOMOLOGADO",
            "risco":"Não inferir porto, fluxo rodoviário, município produtor, operação realizada ou custo nacional"}
