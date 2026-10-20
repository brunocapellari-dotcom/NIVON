"""IVO: consulta read-only de Parquet local autorizado via DuckDB opcional.

Não aceita SQL livre e não baixa dados. Query de colunas fixas parametrizada,
limites de arquivo/linhas, caminhos sem symlink e snapshot bitemporal NIVON.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable

from .historico import Observacao, visao_na_data


class ErroParquet(ValueError):
    pass


CAMPOS = (
    "fonte","variavel","produto","regiao","unidade","competencia",
    "calendario","referencia","publicacao","coleta","valor","natureza","edicao",
)
CONSULTA = (
    "SELECT fonte,variavel,produto,regiao,unidade,competencia,calendario,"
    "referencia,publicacao,coleta,valor,natureza,edicao "
    "FROM read_parquet(?) "
    "WHERE fonte=? AND variavel=? AND produto=? AND regiao=? AND unidade=? "
    "LIMIT ?"
)


def _texto(v,nome):
    if not isinstance(v,str) or not v.strip() or len(v)>160:
        raise ErroParquet(f"{nome} inválido")
    return v


def _instante(v,nome):
    if not isinstance(v,datetime):
        try:v=datetime.fromisoformat(v)
        except (TypeError,ValueError) as exc:raise ErroParquet(f"{nome} inválido") from exc
    if v.tzinfo is None or v.utcoffset() is None:
        raise ErroParquet(f"{nome} sem fuso horário")
    return v.astimezone(timezone.utc)


def _data(v,nome):
    if isinstance(v,datetime):
        raise ErroParquet(f"{nome}: requer dia explícito sem hora")
    if isinstance(v,date):
        return v
    if isinstance(v,str):
        try:return date.fromisoformat(v)
        except ValueError: pass
    raise ErroParquet(f"{nome}: data inválida")


def _arquivo(root,relative,max_bytes):
    if not isinstance(root,(str,Path)) or not isinstance(relative,str):
        raise ErroParquet("raiz ou arquivo inválido")
    base=Path(root).expanduser()
    rel=Path(relative)
    if (base.is_symlink() or not base.is_dir() or rel.is_absolute() or
            len(rel.parts)==0 or any(p in ("..",".") for p in rel.parts) or
            rel.suffix.lower()!=".parquet"):
        raise ErroParquet("arquivo Parquet deve estar dentro de diretório autorizado")
    path=base
    for token in rel.parts:
        path=path/token
        if path.is_symlink():
            raise ErroParquet("symlink de arquivo/diretório proibido")
    absbase=base.resolve(strict=True)
    resolved=path.resolve(strict=True)
    if not resolved.is_relative_to(absbase) or not resolved.is_file():
        raise ErroParquet("arquivo fora do diretório de dados autorizado")
    length=resolved.stat().st_size
    if not 0 < length <= max_bytes:
        raise ErroParquet("tamanho de Parquet fora dos limites")
    return resolved,length


def _run_duckdb(query,args):
    try:import duckdb
    except ImportError as exc:
        raise RuntimeError("DuckDB opcional ausente: instale ivo-query explicitamente") from exc
    con=duckdb.connect(database=":memory:")
    try:
        return con.execute(query,args).fetchall()
    finally:
        con.close()


def carregar_asof_parquet(
    *, diretorio:str|Path,arquivo:str, fonte:str,variavel:str,produto:str,
    regiao:str,unidade:str, corte_publicacao:date,corte_coleta:datetime,
    acesso_autorizado:bool=False,max_linhas:int=5000,
    max_bytes:int=64*1024*1024,executor:Callable|None=None,
)->dict:
    """Extrai apenas registros da série e devolve visão temporal NIVON.

    O executor injetado destina-se exclusivamente a testes; o código não
    substitui a auditoria dos direitos de cada fonte/dataset externo.
    """
    if acesso_autorizado is not True:
        raise PermissionError("dados locais sem acesso autorizado")
    if type(max_linhas) is not int or not 1<=max_linhas<=50000:
        raise ErroParquet("limite de linhas inválido")
    if type(max_bytes) is not int or not 1024<=max_bytes<=256*1024*1024:
        raise ErroParquet("limite de bytes inválido")
    for label,value in (("fonte",fonte),("variavel",variavel),
                        ("produto",produto),("regiao",regiao),("unidade",unidade)):
        _texto(value,label)
    if not isinstance(corte_publicacao,date) or isinstance(corte_publicacao,datetime):
        raise ErroParquet("corte publicação exige date")
    cutoff=_instante(corte_coleta,"corte_coleta")
    if executor is not None and not callable(executor):
        raise ErroParquet("executor inválido")
    path,size=_arquivo(diretorio,arquivo,max_bytes)
    sqlargs=[str(path),fonte,variavel,produto,regiao,unidade,max_linhas+1]
    rows=(executor or _run_duckdb)(CONSULTA,sqlargs)
    if not isinstance(rows,(tuple,list)) or len(rows)>max_linhas:
        raise ErroParquet("resultado excessivo ou inválido")
    observacoes=[]
    for row in rows:
        if not isinstance(row,(tuple,list)) or len(row)!=len(CAMPOS):
            raise ErroParquet("layout de arquivo diferente do contrato NIVON")
        dado=dict(zip(CAMPOS,row))
        if any(dado[n]!=v for n,v in (
            ("fonte",fonte),("variavel",variavel),("produto",produto),
            ("regiao",regiao),("unidade",unidade))):
            raise ErroParquet("executor retornou registros fora do escopo")
        try:
            observacoes.append(Observacao(
                fonte=fonte,variavel=variavel,produto=produto,regiao=regiao,
                unidade=unidade,competencia=dado["competencia"],
                calendario=dado["calendario"],referencia=_data(dado["referencia"],"referencia"),
                publicacao=_data(dado["publicacao"],"publicacao"),
                coleta=_instante(dado["coleta"],"coleta"),
                valor=dado["valor"],natureza=dado["natureza"],edicao=dado["edicao"] or "",
            ))
        except ValueError as exc:
            raise ErroParquet("observação Parquet viola contrato temporal") from exc
    selecionadas=visao_na_data(observacoes,data_corte_publicacao=corte_publicacao,
                                instante_corte_coleta=cutoff)
    # SHA de bytes reais, não de string/path inventado.
    digest=sha256()
    with path.open("rb") as stream:
        while True:
            block=stream.read(1024*1024)
            if not block:break
            digest.update(block)
    if path.stat().st_size!=size:
        raise ErroParquet("arquivo mudou durante a consulta")
    return {
        "estado":"VISAO_PARQUET_OFFLINE_NAO_HOMOLOGADA",
        "arquivo_sha256":digest.hexdigest(),"tamanho_bytes":size,
        "linhas_consultadas":len(observacoes),"linhas_asof":len(selecionadas),
        "corte_publicacao":corte_publicacao.isoformat(),
        "corte_coleta":cutoff.isoformat(),"observacoes":selecionadas,
        "origem_validada_automaticamente":False,
        "redistribuicao_comercial_autorizada":False,
    }
