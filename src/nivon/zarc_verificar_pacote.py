"""Validador independente do pacote ZARC recebido pelo Drive ou artifact.

Streaming por SHA dos dois arquivos comprimidos e dos dados originais,
contagem de linhas MT e integridade do JSON/sha por registro, sem acessar
rede ou interpretar riscos agrícolas.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

from .zarc_stream_mt import COLUNAS, MAX_DOWNLOAD

SHA=re.compile(r"[a-f0-9]{64}\Z")
MAX_PACKED=230_000_000
MAX_MT_LINES=300_000

class ErroVerificacaoPacoteZarc(ValueError):
    pass

def _checksum(p):
    sha=hashlib.sha256()
    size=0
    with p.open("rb") as stream:
        while True:
            b=stream.read(256*1024)
            if not b:
                break
            sha.update(b)
            size+=len(b)
            if size>MAX_PACKED:
                raise ErroVerificacaoPacoteZarc("PACOTE_EXCEDE_LIMITE")
    return sha.hexdigest(),size

def _hash_obj(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,
                   separators=(",",":")).encode("utf-8")).hexdigest()

def verificar_pacote(diretorio):
    root=Path(diretorio)
    if not root.is_dir() or root.is_symlink():
        raise ErroVerificacaoPacoteZarc("DIRETORIO_INVALIDO")
    manifest_path=root/"manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ErroVerificacaoPacoteZarc("MANIFESTO_NAO_ENCONTRADO")
    if manifest_path.stat().st_size>100_000:
        raise ErroVerificacaoPacoteZarc("MANIFESTO_EXCESSIVO")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    sha=manifest.get("source_csv_sha256")
    if (manifest.get("schema")!="NIVON_ZARC_PACOTE_REAL_V1"
        or manifest.get("dataset_id")!="ZARC_JANELAS"
        or manifest.get("licenca")!="cc-by"
        or manifest.get("publicavel") is not False
        or manifest.get("postgres_agricola_atualizado") is not False
        or not isinstance(sha,str) or not SHA.fullmatch(sha)):
        raise ErroVerificacaoPacoteZarc("MANIFESTO_SEM_GARANTIAS")
    paths={}
    for key,suffix in (("raw_gzip",".csv.gz"),("mt_jsonl_gzip",".mt.jsonl.gz")):
        info=manifest.get(key)
        if not isinstance(info,dict) or info.get("filename")!=sha+suffix:
            raise ErroVerificacaoPacoteZarc("ARQUIVO_NAO_CANONICO")
        p=root/info["filename"]
        if p.is_symlink() or not p.is_file():
            raise ErroVerificacaoPacoteZarc("ARQUIVO_AUSENTE_OU_LINK")
        h,n=_checksum(p)
        if h!=info.get("sha256") or n!=info.get("bytes"):
            raise ErroVerificacaoPacoteZarc("HASH_COMPACTADO_DIVERGENTE")
        paths[key]=p
    h=hashlib.sha256()
    total=0
    with gzip.open(paths["raw_gzip"],"rb") as stream:
        while True:
            b=stream.read(256*1024)
            if not b:
                break
            total+=len(b)
            if total>MAX_DOWNLOAD:
                raise ErroVerificacaoPacoteZarc("CSV_DESCOMPACTADO_EXCESSIVO")
            h.update(b)
    if h.hexdigest()!=sha or total!=manifest.get("source_csv_bytes"):
        raise ErroVerificacaoPacoteZarc("SHA_ORIGINAL_DIVERGENTE")
    number=0
    last=0
    mun=set()
    try:
        with gzip.open(paths["mt_jsonl_gzip"],"rt",encoding="utf-8") as stream:
            for line in stream:
                number+=1
                if number>MAX_MT_LINES:
                    raise ErroVerificacaoPacoteZarc("MT_LINHAS_EXCESSIVAS")
                if len(line)>30_000:
                    raise ErroVerificacaoPacoteZarc("JSONL_LINHA_EXCESSIVA")
                obj=json.loads(line)
                i=obj.get("linha_fisica")
                fields=obj.get("campos_csv")
                if (not isinstance(i,int) or i<=last or
                    obj.get("source_sha256")!=sha or not isinstance(fields,dict)
                    or set(fields)!=set(COLUNAS)
                    or fields.get("UF")!="MT"
                    or not all(isinstance(v,str) for v in fields.values())
                    or _hash_obj(fields)!=obj.get("conteudo_sha")):
                    raise ErroVerificacaoPacoteZarc("DADOS_MT_HISTORICOS_DIVERGENTES")
                last=i
                mun.add(fields["geocodigo"])
    except (UnicodeError,gzip.BadGzipFile,EOFError) as exc:
        raise ErroVerificacaoPacoteZarc("ARQUIVO_MT_NAO_VALIDO") from None
    if (number!=manifest.get("mt_linhas")
        or len(mun)!=manifest.get("mt_municipios")):
        raise ErroVerificacaoPacoteZarc("CONTAGENS_MT_DIVERGENTES")
    return {
       "dataset_id":"ZARC_JANELAS",
       "sha256_csv_integral":sha,
       "bytes_csv_integral":total,
       "mt_linhas":number,
       "mt_municipios":len(mun),
       "arquivos_compactados_verificados":2,
       "estado":"INTEGRIDADE_LOCAL_DE_ARQUIVO_CC_BY_VERIFICADA",
       "publicavel":False,
       "persistencia_remota_verificada":False,
    }
