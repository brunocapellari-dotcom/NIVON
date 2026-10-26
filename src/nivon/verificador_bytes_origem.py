"""Prova local dos bytes de origem informados ao ledger NIVON.

Valida hash, tamanho e assinatura básica do arquivo sem persistir ou publicar
payload bruto. NÃO certifica URL de origem, licença ou correção dos parsers.
"""
from __future__ import annotations

import hashlib
import json
import re
from io import BytesIO
from zipfile import BadZipFile, ZipFile

class ErroBytesOrigem(ValueError):
    pass

_MAX = 20_000_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ZIP_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MIMES = frozenset({
    "text/plain","text/csv","application/json","application/pdf",
    "application/vnd.ms-excel",_ZIP_MIME,
})

def conferir_bytes_origem(*,payload:bytes,sha256_informado:str,
                         tamanho_informado:int,mime:str)->dict:
    if not isinstance(payload,bytes) or not 0<len(payload)<=_MAX:
        raise ErroBytesOrigem("arquivo bruto ausente ou maior que 20 MB")
    if type(tamanho_informado) is not int or tamanho_informado!=len(payload):
        raise ErroBytesOrigem("tamanho bruto diverge da evidência")
    if not isinstance(sha256_informado,str) or not _SHA.fullmatch(sha256_informado):
        raise ErroBytesOrigem("SHA-256 informado inválido")
    calculado=hashlib.sha256(payload).hexdigest()
    if calculado!=sha256_informado:
        raise ErroBytesOrigem("SHA-256 diverge dos bytes originais")
    if mime not in _MIMES:
        raise ErroBytesOrigem("MIME sem contrato de inspeção")
    head=payload[:1024].lstrip().lower()
    if head.startswith((b"<html",b"<!doctype html",b"<head",b"<body")):
        raise ErroBytesOrigem("possível bloqueio HTML/WAF disfarçado")
    if mime=="application/pdf":
        if not payload.startswith(b"%PDF-"):
            raise ErroBytesOrigem("PDF sem assinatura")
    elif mime=="application/vnd.ms-excel":
        if not payload.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
            raise ErroBytesOrigem("XLS sem assinatura OLE")
    elif mime==_ZIP_MIME:
        if not payload.startswith(b"PK\x03\x04"):
            raise ErroBytesOrigem("XLSX sem assinatura ZIP")
        try:
            with ZipFile(BytesIO(payload)) as arquivo:
                nomes=arquivo.namelist()
                if (not 2<=len(nomes)<=1000
                    or "[Content_Types].xml" not in nomes
                    or "xl/workbook.xml" not in nomes):
                    raise ErroBytesOrigem("estrutura XLSX incompleta")
                for obj in arquivo.infolist():
                    if (obj.flag_bits & 1 or obj.file_size>30_000_000
                        or obj.file_size > max(obj.compress_size,1)*200
                        or obj.filename.startswith("/")
                        or ".." in obj.filename.split("/")):
                        raise ErroBytesOrigem("XLSX comprimido arriscado ou criptografado")
        except BadZipFile as exc:
            raise ErroBytesOrigem("ZIP/XLSX inválido") from exc
    elif mime=="application/json":
        try:
            valor=json.loads(payload.decode("utf-8-sig"))
        except (UnicodeError,ValueError) as exc:
            raise ErroBytesOrigem("JSON de origem inválido") from exc
        if not isinstance(valor,(list,dict)):
            raise ErroBytesOrigem("JSON origem não é lista ou objeto")
    else:
        if b"\x00" in payload[:4096]:
            raise ErroBytesOrigem("texto de origem parece binário")
    return {"sha256_verificado":calculado,"tamanho_verificado":len(payload),
            "mime_validado_localmente":mime,
            "origem_oficial_comprovada":False,"direitos_de_uso_comprovados":False,
            "parser_vs_bruto_conciliado":False}
