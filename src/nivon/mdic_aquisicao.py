"""Aquisição supervisionada de CSV MDIC anual: streaming, limites e arquivo imutável.

Sem agendamento ou HTTP automático; requer opt-in, direitos documentados e
catálogo operacional explicitamente habilitado. Testes injetam abridor falso.
O índice oficial determina quais URLs foram observadas, sem construí-las
por suposição. Nenhuma publicação ou homologação implícita.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .mdic_manifesto import INDEX, _LINKS

class ErroDownloadMDIC(ValueError):
    pass

class _NaoRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None

_MIMES=frozenset({"text/csv","text/plain","application/csv",
                  "application/octet-stream","application/vnd.ms-excel"})
_SHA=re.compile(r"[0-9a-f]{64}\Z")
_EVIDENCIA=re.compile(r"[A-Za-z0-9._:/-]{6,160}\Z")

def _url_esperada(item:dict)->tuple[str,str,str]:
    if not isinstance(item,dict) or item.get("estado")!="LINK_OFICIAL_DESCOBERTO_SEM_DOWNLOAD":
        raise ErroDownloadMDIC("item MDIC fora do contrato de descoberta")
    direcao,gran=item.get("direcao"),item.get("granularidade")
    padrao=_LINKS.get((direcao,gran))
    ano=item.get("ano")
    if padrao is None or type(ano) is not int or not 1997<=ano<=2100:
        raise ErroDownloadMDIC("direção, granularidade ou ano inválido")
    u=item.get("url")
    if not isinstance(u,str):raise ErroDownloadMDIC("URL ausente")
    p=urlsplit(u)
    if (p.scheme!="https" or p.hostname!="balanca.mdic.gov.br"
        or p.port not in (None,443) or p.username or p.password
        or p.query or p.fragment or p.netloc!="balanca.mdic.gov.br"):
        raise ErroDownloadMDIC("host/URL fora do contrato MDIC")
    m=re.fullmatch(padrao,p.path)
    if m is None or int(m.group(1))!=ano:
        raise ErroDownloadMDIC("caminho anual não coincide com índice")
    filename=p.path.rsplit("/",1)[-1]
    dataset="MDIC_COMEX_NCM" if gran=="NCM" else "MDIC_COMEX_MUNICIPIO_SH4"
    return dataset,u,filename

def baixar_csv_anual_mdic(*,manifesto:dict,item:dict,catalogo:dict,
                          diretorio_privado:str|Path,
                          direitos:frozenset[str]=frozenset(),
                          evidencia_direitos:str|None=None,
                          permitir_rede:bool=False,
                          abridor=None,limite_bytes:int=1_500_000_000)->dict:
    """Somente transporta bytes; posterior parser/reconciliação são gates próprios.

    Caminho final: DIRETORIO/dataset/ano/sha256-original/NOME.csv, sem overwrite
    nem exposição em artifacts de CI. Dados não devem ficar no Git público.
    """
    dataset,url,nome=_url_esperada(item)
    if (not isinstance(manifesto,dict) or manifesto.get("fonte")!=INDEX
        or not isinstance(manifesto.get("sha256_html"),str)
        or not _SHA.fullmatch(manifesto["sha256_html"])
        or not isinstance(manifesto.get("arquivos"),list)
        or sum(entrada==item for entrada in manifesto["arquivos"])!=1):
        raise ErroDownloadMDIC("URL não comprovada pelo manifesto de índice recebido")
    if not isinstance(catalogo,dict) or not isinstance(catalogo.get("datasets"),list):
        raise ErroDownloadMDIC("catálogo inválido")
    entradas=[x for x in catalogo["datasets"] if x.get("id")==dataset]
    if (len(entradas)!=1 or entradas[0].get("enabled") is not True
        or entradas[0].get("collection_authorized") is not True):
        raise PermissionError("dataset MDIC inativo: proibido acessar rede")
    if (not isinstance(direitos,frozenset)
        or not {"COLETA","ARMAZENAMENTO"}.issubset(direitos)
        or not isinstance(evidencia_direitos,str)
        or not _EVIDENCIA.fullmatch(evidencia_direitos)):
        raise PermissionError("direitos de coleta/armazenamento sem comprovação")
    if permitir_rede is not True:
        raise PermissionError("transferência desativada: opt-in explícito obrigatório")
    if type(limite_bytes) is not int or not 0<limite_bytes<=1_500_000_000:
        raise ErroDownloadMDIC("limite de arquivo inválido")
    root=Path(diretorio_privado)
    if root.is_symlink() or not root.is_dir() or not stat.S_ISDIR(root.stat().st_mode):
        raise ErroDownloadMDIC("destino privado precisa existir e não pode ser symlink")
    if root.stat().st_mode & 0o077:
        raise PermissionError("diretório deve ser privado: chmod 700 antes da coleta")
    client=abridor if abridor is not None else build_opener(_NaoRedirecionar())
    req=Request(url,headers={"User-Agent":"NIVON/0.3 MDIC opt-in",
                             "Accept":"text/csv,text/plain,application/octet-stream"})
    tmp=None
    try:
        with client.open(req,timeout=30) as response:
            if int(response.status)!=200 or response.geturl()!=url:
                raise ErroDownloadMDIC("status ou redirecionamento não autorizado")
            mime=str(response.headers.get("Content-Type","")).lower().split(";",1)[0].strip()
            if mime not in _MIMES:
                raise ErroDownloadMDIC("Content-Type fora do contrato de CSV")
            stated=response.headers.get("Content-Length")
            if stated not in (None,""):
                try: declared=int(stated)
                except ValueError as exc:
                    raise ErroDownloadMDIC("Content-Length não numérico") from exc
                if declared<=0 or declared>limite_bytes:
                    raise ErroDownloadMDIC("arquivo remoto fora dos limites")
            else:declared=None
            hashv=hashlib.sha256()
            total=0
            with tempfile.NamedTemporaryFile(mode="wb",prefix=".nivon-mdic-",
                   suffix=".partial",dir=root,delete=False) as dst:
                tmp=Path(dst.name)
                os.chmod(tmp,0o600)
                while True:
                    bloco=response.read(min(262144,limite_bytes-total+1))
                    if not bloco:break
                    total+=len(bloco)
                    if total>limite_bytes:
                        raise ErroDownloadMDIC("download excedeu limite")
                    if total==len(bloco) and (bloco[:2048].lstrip().lower().startswith(
                        (b"<html",b"<!doctype html",b"request rejected",b"access denied"))):
                        raise ErroDownloadMDIC("HTML/WAF disfarçado de CSV")
                    if b"\x00" in bloco[:4096]:
                        raise ErroDownloadMDIC("conteúdo binário não é CSV")
                    hashv.update(bloco)
                    dst.write(bloco)
                dst.flush()
                os.fsync(dst.fileno())
        if not total or (declared is not None and declared!=total):
            raise ErroDownloadMDIC("download vazio/truncado segundo Content-Length")
        sha=hashv.hexdigest()
        target=root/dataset/str(item["ano"])/sha
        target.mkdir(mode=0o700,parents=True,exist_ok=True)
        if target.is_symlink() or target.stat().st_mode & 0o077:
            raise PermissionError("diretório de versão não é privado")
        final=target/nome
        try:
            # Hardlink atômico falha se a edição já existe; nunca substituir.
            os.link(tmp,final,follow_symlinks=False)
        except FileExistsError:
            if final.is_symlink() or not final.is_file() or final.stat().st_size!=total:
                raise ErroDownloadMDIC("edição existente divergente ou insegura")
            current=hashlib.sha256()
            with final.open("rb") as f:
                for block in iter(lambda:f.read(262144),b""):
                    current.update(block)
            if current.hexdigest()!=sha:
                raise ErroDownloadMDIC("edição existente com hash divergente")
        return {"dataset_id":dataset,"ano":item["ano"],"direcao":item["direcao"],
                "granularidade":item["granularidade"],"origem":url,
                "sha256":sha,"bytes":total,"arquivo_local":str(final),
                "mime":mime,"arquivo_publicado_ou_homologado":False,
                "download_supervisionado":True,
                "evidencia_direitos_informada":evidencia_direitos}
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)
