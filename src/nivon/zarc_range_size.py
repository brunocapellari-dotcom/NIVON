"""Diagnóstico leve para tamanho de CSV ZARC via HTTP Range: nenhum dado salvo.

Um GET Range=bytes=0-0, no máximo um byte lido. Se servidor ignorar
Range, o tamanho seguirá DESCONHECIDO e processamento integral continua OFF.
"""
from __future__ import annotations
import re
from urllib.request import Request, build_opener
from .zarc_stream_mt import URL, MAX_DOWNLOAD, _NoRedirect

class ErroZarcTamanho(ValueError):
    pass

_CONTENT_RANGE = re.compile(r"bytes 0-0/([1-9]\d{0,13}|\*)\Z")

def interpretar_resposta(*, url, status, mime, content_range, content_length, primeiro_byte):
    if url != URL or status not in (200, 206):
        raise ErroZarcTamanho("ORIGEM_OU_STATUS_DIVERGENTE")
    if mime.lower().strip() not in ("text/csv","text/plain","application/octet-stream","application/csv"):
        raise ErroZarcTamanho("MIME_NAO_CSV")
    if not isinstance(primeiro_byte, bytes) or len(primeiro_byte) != 1:
        raise ErroZarcTamanho("PRIMEIRO_BYTE_INVALIDO")
    total = None
    if status == 206:
        m=_CONTENT_RANGE.fullmatch(str(content_range or ""))
        if not m:
            raise ErroZarcTamanho("CONTENT_RANGE_INVALIDO")
        if m.group(1) != "*":
            total = int(m.group(1))
    elif content_length is not None:
        if not isinstance(content_length, str) or not re.fullmatch(r"\d{1,14}", content_length):
            raise ErroZarcTamanho("CONTENT_LENGTH_INVALIDO")
        total = int(content_length)
    if total is not None and total < 1:
        raise ErroZarcTamanho("TAMANHO_INVALIDO")
    return {"estado": "PROVA_DE_CABECALHO_NAO_ARQUIVO",
            "status_http": status, "http_range_atendido": status == 206,
            "total_bytes_comprovado": total,
            "maior_que_limite_atual": total > MAX_DOWNLOAD if total is not None else None,
            "max_download_bytes": MAX_DOWNLOAD,
            "corpo_transferido_bytes": 1,
            "coleta_persistida": False, "arquivo_integral_baixado": False}

def consultar_tamanho(*, executar=False, abridor=None):
    if executar is not True:
        raise PermissionError("REDE_OFF")
    req=Request(URL, headers={"Accept":"text/csv", "Range":"bytes=0-0",
                              "User-Agent":"NIVON/0.1 (uso-nao-comercial)"})
    cliente=abridor if abridor is not None else build_opener(_NoRedirect())
    with cliente.open(req, timeout=20) as resp:
        status=int(resp.status)
        destino=resp.geturl()
        mime=str(resp.headers.get("Content-Type","")).split(";",1)[0].strip().lower()
        cr=resp.headers.get("Content-Range")
        cl=resp.headers.get("Content-Length")
        byte=resp.read(1)
    return interpretar_resposta(url=destino,status=status,mime=mime,
                                content_range=cr,content_length=cl,primeiro_byte=byte)
