"""Pacote ZARC REAL para transferência segura GitHub artifact -> Drive privado.

Lê CSV do MAPA, valida licença CKAN, retém RAW gzip determinístico e dados
MT JSONL gzip como EVIDÊNCIA, sem marcar publicação e sem escrever Neon.
Os arquivos de saída são retornados somente como artefatos Actions,
nunca commitados ao repositório. O consumidor deve revalidar hashes.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .catalogo_fontes import carregar_catalogo
from .fontes_abertas_lote import consultar
from .zarc_ensaio_real import obter_csv_temporario
from .zarc_licenca_manual import emitir_licenca_manual
from .zarc_raw_vault import guardar_raw_zarc, verificar_raw_zarc
from .zarc_sinais_ckan import normalizar_sinal
from .zarc_staging import abrir_zarc_staging, importar_zarc_local
from .zarc_stream_mt import URL, COLUNAS

SHA=re.compile(r"[0-9a-f]{64}\Z")

class ErroPacoteZarc(ValueError):
    pass

def _sha_path(path):
    h=hashlib.sha256()
    n=0
    with Path(path).open("rb") as f:
        for piece in iter(lambda:f.read(262144),b""):
            h.update(piece)
            n+=len(piece)
    return h.hexdigest(),n

def _gzip_csv(src,destino):
    """Compressão reprodutível; sem data ou nome do arquivo no cabeçalho."""
    with Path(src).open("rb") as src_stream,Path(destino).open("xb") as target:
        with gzip.GzipFile(filename="",mode="wb",fileobj=target,compresslevel=6,mtime=0) as output:
            shutil.copyfileobj(src_stream,output,length=262144)
        target.flush()
        os.fsync(target.fileno())

def _exportar_mt_jsonl(db,sha,arquivo):
    n=0
    with Path(arquivo).open("xb") as raw:
        with gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0,compresslevel=6) as gz:
            for row in db.execute("""SELECT linha_fisica,conteudo_sha,chave_logica_sha,
                  dados_raw_json FROM zarc_linhas WHERE sha256=?
                  ORDER BY linha_fisica""",(sha,)):
                fields=json.loads(row[3])
                if (not isinstance(fields,dict) or len(fields)!=len(COLUNAS)
                        or set(fields)!=set(COLUNAS)):
                    raise ErroPacoteZarc("LINHA_MT_DIVERGE_DO_LAYOUT")
                data={"source_sha256":sha,"linha_fisica":row[0],
                      "conteudo_sha":row[1],"chave_logica_sha":row[2],
                      "campos_csv":fields}
                gz.write((json.dumps(data,ensure_ascii=False,sort_keys=True,
                         separators=(",",":"))+"\n").encode("utf-8"))
                n+=1
        raw.flush()
        os.fsync(raw.fileno())
    return n

def criar_pacote(*,destino,executar=False,consulta_ckan=None,
                 downloader=None,instante=None):
    if executar is not True:
        raise PermissionError("PACOTE_REAL_REQUER_EXECUCAO_MANUAL")
    path=Path(destino)
    if not path.is_absolute() or path.is_symlink():
        raise ErroPacoteZarc("DIRETORIO_DEVE_SER_ABSOLUTO")
    if not path.is_dir() or list(path.iterdir()):
        raise ErroPacoteZarc("PASTA_ARTIFACT_DEVE_ESTAR_VAZIA")
    now=instante if instante is not None else datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None:
        raise ErroPacoteZarc("COLETA_SEM_FUSO")
    provider=consulta_ckan or (lambda:consultar("MAPA_ZARC",executar=True))
    sinal=normalizar_sinal(provider())
    permit=emitir_licenca_manual(sinal,consentimento_manual=True)
    temp=None
    try:
        with tempfile.TemporaryDirectory(prefix="nivon-zarc-artifact-") as work:
            root=Path(work)
            tmp_csv=root/"origem.csv"
            got=(downloader or obter_csv_temporario)(destino=tmp_csv,executar=True)
            if not isinstance(got,dict) or not SHA.fullmatch(str(got.get("sha256",""))):
                raise ErroPacoteZarc("DOWNLOAD_SEM_SHA")
            vault=root/"raw"
            vault.mkdir(mode=0o700)
            with abrir_zarc_staging() as db:
                with tmp_csv.open("rb") as f:
                    result=importar_zarc_local(db,carregar_catalogo(),f,
                      coletado_em=now.astimezone(timezone.utc).isoformat(),
                      origem="REAL_AUTORIZADO",
                      autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                      evidencia_direitos=permit.evidence_id,
                      licenca_manual=permit)
                with tmp_csv.open("rb") as f:
                    guardar_raw_zarc(db=db,arquivo=f,raiz=vault)
                proof=verificar_raw_zarc(db=db,raiz=vault,
                                         sha256=result["sha256"])
                if (got["sha256"]!=result["sha256"]
                        or got["bytes"]!=proof["bytes"]):
                    raise ErroPacoteZarc("PROVA_RAW_NAO_CONFERIU")
                sha=result["sha256"]
                raw_name=f"{sha}.csv.gz"
                mt_name=f"{sha}.mt.jsonl.gz"
                raw_path=path/raw_name
                mt_path=path/mt_name
                _gzip_csv(vault/(sha+".csv"),raw_path)
                rows=_exportar_mt_jsonl(db,sha,mt_path)
                if rows!=result["linhas_mt"]:
                    raise ErroPacoteZarc("LINHAS_MT_EXPORTADAS_DIVERGENTES")
                raw_gz_sha,raw_gz_bytes=_sha_path(raw_path)
                mt_sha,mt_bytes=_sha_path(mt_path)
                manifest={
                   "schema":"NIVON_ZARC_PACOTE_REAL_V1",
                   "dataset_id":"ZARC_JANELAS",
                   "fonte":"MAPA / Zoneamento Agricola de Risco Climatico",
                   "fonte_url":URL,
                   "licenca":"cc-by","atribuicao_obrigatoria":True,
                   "licenca_evidencia":permit.evidence_id,
                   "metadata_ckan_fingerprint":sinal["metadata_fingerprint"],
                   "resource_ckan_revision":sinal["recurso_revision_id"],
                   "competencia":"2026/2027",
                   "data_referencia":None,"data_publicacao":None,
                   "coletado_em":now.astimezone(timezone.utc).isoformat(),
                   "source_csv_sha256":sha,
                   "source_csv_bytes":result["bytes"],
                   "brasil_linhas":result["linhas_total"],
                   "mt_linhas":result["linhas_mt"],
                   "mt_municipios":result["municipios_mt"],
                   "raw_gzip":{"filename":raw_name,
                               "sha256":raw_gz_sha,"bytes":raw_gz_bytes},
                   "mt_jsonl_gzip":{"filename":mt_name,
                                   "sha256":mt_sha,"bytes":mt_bytes,"linhas":rows},
                   "github_run_id":os.environ.get("GITHUB_RUN_ID"),
                   "github_commit":os.environ.get("GITHUB_SHA"),
                   "classificacao":"ARQUIVO_REAL_SEM_HOMOLOGACAO_AGRONOMICA",
                   "source_csv_hash_verificado":True,
                   "publicavel":False,"apto_backtest":False,
                   "postgres_agricola_atualizado":False,
                   "storage_neon_arquivado":False,
                }
                # Não incluir URLs assinadas, credenciais ou PII.
                manifest_path=path/"manifest.json"
                manifest_path.write_text(json.dumps(
                    manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n",
                    encoding="utf-8")
                os.chmod(manifest_path,0o600)
                return {
                    "dataset_id":"ZARC_JANELAS","csv_sha256":sha,
                    "mt_linhas":rows,"mt_municipios":result["municipios_mt"],
                    "csv_bytes":result["bytes"],
                    "raw_gzip_bytes":raw_gz_bytes,"mt_gzip_bytes":mt_bytes,
                    "pacote_preparado":True,
                    "arquivo_persistente_drive":False,
                    "arquivo_neon_bucket":False,
                    "postgres_linhas_gravadas":False,
                    "publicavel":False}
    except BaseException:
        for f in path.glob("*"):
            if f.is_file() and not f.is_symlink():
                f.unlink(missing_ok=True)
        raise

def main():
    target=os.environ.get("NIVON_ZARC_ARTIFACT_DIR")
    if not target:
        raise PermissionError("FALTA_DIRETORIO_SEGURO_ARTIFACT")
    out=criar_pacote(destino=target,executar=True)
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
