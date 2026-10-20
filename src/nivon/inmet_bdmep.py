"""Link privado BDMEP recebido por e-mail: validação e download opt-in.

O URL funciona como segredo de acesso e nunca deve constar em logs,
GitHub, CI, comandos de shell ou artefatos públicos. Não há rede por padrão.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

class ErroBDMEP(ValueError):
    pass

_MAX_BYTES=80_000_000
_HOST="bdmep.inmet.gov.br"
_RECURSO=re.compile(r"/\$2[aby]\$[0-9]{2}\$[A-Za-z0-9./]{40,100}\.zip\Z")

class _SemRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _url_privada(valor):
    if not isinstance(valor,str):
        raise ErroBDMEP("URL da solicitação BDMEP ausente")
    p=urlsplit(valor)
    if (p.scheme!="https" or p.hostname!=_HOST or p.username or p.password
        or p.query or p.fragment or p.port not in (None,443)
        or not _RECURSO.fullmatch(p.path)):
        raise ErroBDMEP("URL não corresponde a solicitação BDMEP segura")
    return valor

def link_privado_do_ambiente():
    return _url_privada(os.environ.get("NIVON_INMET_BDMEP_URL",""))

def conferir_zip_bdmep(caminho):
    """Verifica compactado privado em disco SEM extrair nem decodificar dados."""
    from .inmet_historico import _inventario
    p=Path(caminho)
    if p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<=_MAX_BYTES:
        raise ErroBDMEP("ZIP inexistente ou maior que limite")
    try:
        with zipfile.ZipFile(p) as z:
            csv,total,membros=_inventario(z)
    except (OSError,RuntimeError,zipfile.BadZipFile,ValueError) as exc:
        raise ErroBDMEP("ZIP inválido ou perigoso") from exc
    return {"membros":membros,"csv":len(csv),"bytes_descompactados":total,
            "autorizado_para_publicacao":False,"parser_aceito":False}

def receber_bdmep(*,pasta_privada,habilitar_rede=False,url=None,transporte=None,
                  max_bytes=_MAX_BYTES):
    """Salva em local privado somente em operação explicitamente autorizada.

    Retorna somente hash/caminho privado/tamanho, nunca o URL tokenizado.
    O usuário precisa disponibilizar o link ao executor via secret vault.
    """
    if not habilitar_rede:
        raise PermissionError("download BDMEP desligado por padrão")
    privado=_url_privada(url if url is not None else link_privado_do_ambiente())
    if type(max_bytes) is not int or not 1024<=max_bytes<=_MAX_BYTES:
        raise ErroBDMEP("limite de download inválido")
    pasta=Path(pasta_privada)
    if pasta.is_symlink() or not pasta.is_dir() or (pasta.stat().st_mode & stat.S_IWOTH):
        raise ErroBDMEP("pasta privada deve existir e não pode ser pública/gravação universal")
    fd,tmp=tempfile.mkstemp(prefix=".nivon-bdmep-",suffix=".zip",dir=pasta)
    os.fchmod(fd,0o600)
    caminho=Path(tmp)
    sha=hashlib.sha256()
    total=0
    try:
        opener=transporte or build_opener(_SemRedirecionar())
        req=Request(privado,headers={"Accept":"application/zip"},method="GET")
        with opener.open(req,timeout=20) as resposta:
            if getattr(resposta,"status",None)!=200:
                raise ErroBDMEP("BDMEP não forneceu arquivo 200")
            with os.fdopen(fd,"wb") as arq:
                fd=-1
                while True:
                    chunk=resposta.read(min(64_000,max_bytes-total+1))
                    if not chunk:break
                    total+=len(chunk)
                    if total>max_bytes:
                        raise ErroBDMEP("tamanho do download excedeu limite")
                    arq.write(chunk)
                    sha.update(chunk)
                arq.flush()
                os.fsync(arq.fileno())
        if total==0:
            raise ErroBDMEP("BDMEP retornou arquivo vazio")
        schema=conferir_zip_bdmep(caminho)
        destino=pasta/("bdmep_"+sha.hexdigest()+".zip")
        if destino.exists() or destino.is_symlink():
            raise ErroBDMEP("arquivo existente: sem sobrescrita automática")
        os.link(caminho,destino)
        return {"caminho_privado":str(destino),"sha256":sha.hexdigest(),
                "bytes":total,"inventario":schema,"conteudo_publicado":False}
    except (OSError,RuntimeError,zipfile.BadZipFile) as exc:
        raise ErroBDMEP("falha ao receber ou validar arquivo BDMEP") from None
    finally:
        if fd>=0:os.close(fd)
        caminho.unlink(missing_ok=True)
