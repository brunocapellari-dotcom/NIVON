"""Inspeção semântica, limitada a 8 MiB, do começo do ZARC 2026/27.

Servidor público pode ignorar Range e omitir Content-Length. Por isso faz
UM GET, lê no máximo 8 MiB, interrompe a leitura e fecha o corpo.
Não assume que as linhas do início representam todo o Brasil/MT.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from urllib.request import Request, build_opener
from .zarc_stream_mt import URL, COLUNAS, _NoRedirect

LIMITE = 8 * 1024 * 1024
class ErroZarcAmostra(ValueError):
    pass

def examinar_prefixo(blob: bytes) -> dict:
    if not isinstance(blob, bytes) or not 1 <= len(blob) <= LIMITE:
        raise ErroZarcAmostra("BLOCO_INVALIDO")
    fim = blob.rfind(b"\n")
    if fim < 0:
        raise ErroZarcAmostra("SEM_LINHAS_TERMINADAS")
    bloco=blob[:fim + 1]
    try:
        txt=bloco.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ErroZarcAmostra("NAO_UTF8") from exc
    reader = csv.DictReader(io.StringIO(txt), delimiter=";", restkey="_extra", restval=None)
    if reader.fieldnames != list(COLUNAS):
        raise ErroZarcAmostra("SCHEMA_55_COLUNAS_DIVERGENTE")
    total=0
    mt=0
    counts=Counter()
    ufs=Counter()
    for row in reader:
        total+=1
        if "_extra" in row or any(v is None for v in row.values()) or len(row)!=len(COLUNAS):
            counts["CSV_DESALINHADO"]+=1
            continue
        uf=row["UF"].strip()
        ufs[uf]+=1
        if uf!="MT":
            continue
        mt+=1
        if not re.fullmatch(r"\d{7}",row["geocodigo"].strip()):
            counts["GEOCODIGO_MT_NAO_IBGE7"]+=1
        if row["SafraIni"].strip()!="2026" or row["SafraFin"].strip()!="2027":
            counts["SAFRA_MT_DIVERGENTE"]+=1
        if not row["Portaria"].strip() or len(row["Portaria"].strip())>300:
            counts["PORTARIA_MT_AUSENTE_OU_LONGA"]+=1
        if not 1<=len(row["Nome_cultura"].strip())<=100:
            counts["CULTURA_MT_INVALIDA"]+=1
        if any(len(row[f"dec{n}"].strip())>100 for n in range(1,37)):
            counts["DECENDIO_MT_EXCESSIVO"]+=1
    return {"estado":"PREFIXO_LIMITADO_NAO_ARQUIVO",
            "bytes_lidos_prefixo":len(blob),
            "bytes_de_linhas_completas":len(bloco),
            "sha256_apenas_prefixo":hashlib.sha256(blob).hexdigest(),
            "colunas_55_confirmadas":True,
            "linhas_completas_amostra":total,
            "linhas_mt_na_amostra":mt,
            "ufs_distintas_na_amostra":len(ufs),
            "regras_que_teriam_bloqueado":dict(counts),
            "amostra_nao_representativa":True,
            "arquivo_integral_lido":False,
            "publicavel":False,"persistido":False}

def consultar_prefixo(*, executar=False, abridor=None, limite=LIMITE):
    if executar is not True:
        raise PermissionError("REDE_OFF")
    if type(limite) is not int or not 4096<=limite<=LIMITE:
        raise ErroZarcAmostra("LIMITE_INVALIDO")
    cli=abridor if abridor is not None else build_opener(_NoRedirect())
    req=Request(URL,headers={"Accept":"text/csv", "Range":f"bytes=0-{limite-1}",
                             "User-Agent":"NIVON/0.1 pesquisa-nao-comercial"})
    with cli.open(req,timeout=35) as res:
        if int(res.status) not in (200,206) or res.geturl()!=URL:
            raise ErroZarcAmostra("ORIGEM_OU_HTTP_INVALIDO")
        mime=str(res.headers.get("Content-Type","")).split(";",1)[0].strip().lower()
        if mime not in {"text/csv","text/plain","application/csv","application/octet-stream"}:
            raise ErroZarcAmostra("MIME_NAO_CSV")
        b=res.read(limite)
        if not isinstance(b,bytes) or not b:
            raise ErroZarcAmostra("CSV_VAZIO")
        status=int(res.status)
    out=examinar_prefixo(b)
    out.update({"http_status":status,"range_atendido":status==206})
    return out

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--executar",action="store_true")
    args=ap.parse_args(argv)
    if not args.executar:
        print(json.dumps({"status":"REDE_OFF"}))
        return 2
    try:
        d=consultar_prefixo(executar=True)
        print(json.dumps(d,sort_keys=True))
        return 0
    except Exception as e:
        print(json.dumps({"estado":"PROVA_NAO_CONCLUIDA","tipo":type(e).__name__}))
        return 1

if __name__=="__main__":
    raise SystemExit(main())
