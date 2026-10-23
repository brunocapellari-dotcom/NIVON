"""Transferência RAW ZARC para Neon Object Storage privado com integridade.

O módulo não gera URLs assinadas, credenciais ou novos recursos. O chamador
precisa obter duas URLs temporárias (PUT e GET) do conector Neon e fornecê-las
somente via canal seguro/ambiente efêmero, NUNCA como argumento de CLI, log ou
commit. Ambas são validadas contra o bucket RAW canônico e SHA esperado.

Após PUT exige GET completo + gzip SHA-256 do CSV original; a checagem não
marca o arquivo como backup remoto até reconstruí-lo e verificá-lo.
"""
from __future__ import annotations

import gzip
import hashlib
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .zarc_raw_vault import verificar_raw_zarc
from .zarc_stream_mt import MAX_DOWNLOAD

HOST="br-restless-paper-b72vbhp7.storage.c-13.us-east-1.aws.neon.tech"
BUCKET="nivon-zarc-raw"
PREFIX="zarc/2026-2027"
MAX_GZIP=MAX_DOWNLOAD
CHUNK=256*1024
_SHA=re.compile(r"[0-9a-f]{64}\Z")

class ErroZarcRemoto(ValueError):
    pass

class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def chave_objeto(sha):
    if not isinstance(sha,str) or not _SHA.fullmatch(sha):
        raise ErroZarcRemoto("SHA_INVALIDO")
    return f"{PREFIX}/{sha}.csv.gz"


def _url_aprovada(url,sha):
    if not isinstance(url,str) or len(url)>3000:
        raise ErroZarcRemoto("URL_ASSINADA_INVALIDA")
    u=urlsplit(url)
    expected=f"/{BUCKET}/{chave_objeto(sha)}"
    if (u.scheme!="https" or u.hostname!=HOST or u.port not in (None,443)
            or u.username or u.password or u.fragment or unquote(u.path)!=expected):
        raise ErroZarcRemoto("URL_NAO_PERTENCE_AO_BUCKET_PRIVADO")
    pairs=parse_qsl(u.query,keep_blank_values=True)
    params={}
    for k,v in pairs:
        if k in params:
            raise ErroZarcRemoto("PARAMETRO_ASSINADO_DUPLICADO")
        params[k]=v
    if (not params.get("X-Amz-Signature")
            or params.get("X-Amz-Algorithm")!="AWS4-HMAC-SHA256"
            or "X-Amz-Expires" not in params
            or not re.fullmatch(r"\d{1,6}",params["X-Amz-Expires"])
            or not 1<=int(params["X-Amz-Expires"])<=604800):
        raise ErroZarcRemoto("ASSINATURA_AWS_INVALIDA")
    return url


def _comprimir_raw(raw_path,output):
    with raw_path.open("rb") as src, output.open("wb") as dst:
        # mtime=0 e filename vazio garantem byte stream reproduzível.
        with gzip.GzipFile(filename="",mode="wb",fileobj=dst,
                           compresslevel=6,mtime=0) as gz:
            for bloco in iter(lambda:src.read(CHUNK),b""):
                gz.write(bloco)
        dst.flush()
        os.fsync(dst.fileno())
    size=output.stat().st_size
    if not 0<size<=MAX_GZIP:
        raise ErroZarcRemoto("GZIP_ULTRAPASSA_LIMITE")
    return size


def _ler_gzip_remoto(resp,sha,expected_bytes):
    if int(resp.status)!=200:
        raise ErroZarcRemoto("GET_NAO_RETORNOU_200")
    h=hashlib.sha256()
    n=0
    try:
        with gzip.GzipFile(fileobj=resp,mode="rb") as gz:
            while True:
                bloco=gz.read(CHUNK)
                if not bloco:
                    break
                n+=len(bloco)
                if n>MAX_DOWNLOAD:
                    raise ErroZarcRemoto("DOWNLOAD_DESCOMPACTADO_EXCESSIVO")
                h.update(bloco)
    except (gzip.BadGzipFile,EOFError,OSError) as exc:
        raise ErroZarcRemoto("ARQUIVO_GZIP_REMOTO_CORROMPIDO") from None
    if n!=expected_bytes or h.hexdigest()!=sha:
        raise ErroZarcRemoto("SHA_CSV_REMOTO_NAO_CONFERE")
    return n


def enviar_raw_neon(*,db,raiz_local,sha256,put_url,get_url,
                    executar=False,abridor=None):
    """PUT + GET de verificação, nunca assume sucesso só por HTTP 200 no PUT."""
    if executar is not True:
        raise PermissionError("ARMAZENAMENTO_REMOTO_DESATIVADO_POR_PADRAO")
    _url_aprovada(put_url,sha256)
    _url_aprovada(get_url,sha256)
    metadata=verificar_raw_zarc(db=db,raiz=raiz_local,sha256=sha256)
    raw=Path(raiz_local)/(sha256+".csv")
    opener=abridor if abridor is not None else build_opener(_SemRedirect())
    with tempfile.TemporaryDirectory(prefix="nivon-neon-raw-") as tempdir:
        packed=Path(tempdir)/"arquivo.csv.gz"
        zipped_size=_comprimir_raw(raw,packed)
        try:
            with packed.open("rb") as stream:
                put=Request(put_url,data=stream,method="PUT",headers={
                    "Content-Type":"application/gzip",
                    "Content-Length":str(zipped_size),
                    "User-Agent":"NIVON/1.0 armazenamento-privado"
                })
                with opener.open(put,timeout=120) as resp:
                    if int(resp.status) not in (200,201,204) or resp.geturl()!=put_url:
                        raise ErroZarcRemoto("PUT_STATUS_OU_REDIRECT_INVALIDO")
            get=Request(get_url,method="GET",headers={
                "Accept":"application/gzip","Accept-Encoding":"identity",
                "User-Agent":"NIVON/1.0 verificacao-integridade"
            })
            with opener.open(get,timeout=120) as resp:
                if resp.geturl()!=get_url:
                    raise ErroZarcRemoto("GET_REDIRECT_INVALIDO")
                verificados=_ler_gzip_remoto(resp,sha256,metadata["bytes"])
        except ErroZarcRemoto:
            raise
        except Exception as exc:
            # urllib errors may contain signed query strings: DO NOT print/re-raise.
            raise ErroZarcRemoto("TRANSFERENCIA_HTTP_NAO_VALIDADA") from None
    return {
        "dataset_id":"ZARC_JANELAS",
        "raw_sha256":sha256,
        "source_bytes":metadata["bytes"],
        "gzip_bytes":zipped_size,
        "bytes_recuperados_e_verificados":verificados,
        "remote_key":chave_objeto(sha256),
        "regiao_storage":"us-east-1",
        "bucket_privado":BUCKET,
        "checagem":"PUT_GET_SHA256_ORIGINAL",
        "objeto_remoto_recuperado_e_verificado":True,
        "durabilidade_independente_auditada":False,
        "backup_independente":False,
        "publicavel":False,
        "inserido_no_banco_agricola":False,
    }
