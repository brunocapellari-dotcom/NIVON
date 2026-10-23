"""Durable Google Cloud bridge: NIVON RAW SQLite -> GCS -> BigQuery.

GCS keeps content-addressed RAW and JSONL before the BigQuery MERGE.
Existing NIVON parser, local collector and BigQuery loader are reused.
No resources are created, no secrets stored, no scheduled calls, no grant of
rights. Quarantined datasets can be backed up to GCS but not written as
canonical BigQuery observations by this bridge.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .carga_bigquery_fontes import planejar_carga
from .ingestao_fontes_reais import exportar_jsonl

_BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
_ID = re.compile(r"^[A-Z][A-Z0-9_]{2,90}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_STATES = frozenset({"NORMALIZED", "RAW_RECEIVED", "QUARANTINED"})
_OPS = frozenset({"COLETA", "ARMAZENAMENTO", "PROCESSAMENTO"})
_MAX_RAW = 25_000_000


class ErroGoogleCloud(ValueError):
    pass


def _hash_file(file: Path) -> str:
    h = hashlib.sha256()
    with file.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def _pack(banco: Path, raw_dir: Path) -> list[dict]:
    if banco.is_symlink() or not banco.is_file() or raw_dir.is_symlink() or not raw_dir.is_dir():
        raise ErroGoogleCloud("SQLite ou diretorio RAW ausente/symlink")
    db = sqlite3.connect(str(banco))
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            """SELECT dataset_id,sha256,snapshot_id,estado,arquivo,
                      tamanho,content_type,coletado_em
                 FROM snapshots ORDER BY dataset_id,sha256"""
        ).fetchall()
    finally:
        db.close()
    if not rows or len(rows) > 300:
        raise ErroGoogleCloud("numero de snapshots fora do limite")
    items=[]
    real_root=raw_dir.resolve(strict=True)
    vistos=set()
    for row in rows:
        ds,sha,snapshot,estado=row["dataset_id"],row["sha256"],row["snapshot_id"],row["estado"]
        if not _ID.fullmatch(ds) or not _SHA.fullmatch(sha) or estado not in _STATES:
            raise ErroGoogleCloud("snapshot com identidade/estado invalido")
        if hashlib.sha256(f"{ds}|{sha}".encode()).hexdigest()!=snapshot:
            raise ErroGoogleCloud("snapshot_id divergente da identidade")
        arquivo=Path(row["arquivo"])
        esperado=real_root/ds/(sha+".raw")
        if (arquivo.is_symlink() or not arquivo.is_file() or
                arquivo.resolve(strict=True)!=esperado or
                not arquivo.resolve(strict=True).is_relative_to(real_root)):
            raise ErroGoogleCloud("path RAW nao pertence ao dataset ou foi manipulado")
        n=arquivo.stat().st_size
        if not 0<n<=_MAX_RAW or n!=row["tamanho"] or _hash_file(arquivo)!=sha:
            raise ErroGoogleCloud("RAW alterado/perdido ou excedeu limite")
        if (ds,sha) in vistos:
            raise ErroGoogleCloud("snapshot duplicado")
        vistos.add((ds,sha))
        items.append({
            "dataset_id":ds,"sha256":sha,"snapshot_id":snapshot,
            "estado":estado,"arquivo":str(arquivo),"bytes":n,
            "content_type":row["content_type"],
            "coletado_em":row["coletado_em"],
            "objeto":f"nivon/raw/{ds}/{sha}.raw",
        })
    return items


def planejar_envio(*, base: str | Path, bucket: str, project_id: str,
                   dataset_id: str, bigquery: bool = True) -> dict:
    """Preflight offline; will not touch storage, HTTP or BigQuery."""
    if not isinstance(bucket,str) or not _BUCKET.fullmatch(bucket):
        raise ErroGoogleCloud("bucket GCS invalido")
    pasta=Path(base)
    items=_pack(pasta/"fontes_reais.sqlite",pasta/"raw")
    estados=sorted(set(item["estado"] for item in items))
    if bigquery and estados!=["NORMALIZED"]:
        raise ErroGoogleCloud("BigQuery bloqueado: lote contem RAW ou QUARENTENA")
    from .carga_bigquery_fontes import PROJECT, DATASET
    if not PROJECT.fullmatch(project_id) or not DATASET.fullmatch(dataset_id):
        raise ErroGoogleCloud("project_id/dataset BigQuery invalidos")
    path = pasta/"staging_fontes_reais.jsonl"
    if bigquery:
        exportar_jsonl(banco=pasta/"fontes_reais.sqlite",destino=path)
        bq=planejar_carga(arquivo=path,project_id=project_id,dataset_id=dataset_id)
        # Exported JSONL must have observations for all valid source snapshots.
        if bq["linhas"]<1:
            raise ErroGoogleCloud("sem observacoes")
    else:
        bq=None
    return {
        "estado":"PREFLIGHT_OK","bucket":bucket,"project_id":project_id,
        "dataset_id":dataset_id,"raw":items, "origem_sqlite":str(pasta/"fontes_reais.sqlite"),
        "bigquery":bq,"bigquery_solicitado":bigquery,
        "gcs_executado":False,"bq_executado":False,
    }


def _enviar_unico(bucket_obj, *, arquivo: Path, objeto: str,
                   sha: str, content_type: str) -> str:
    """Never overwrite an existing object. Verify remote metadata on replay."""
    blob=bucket_obj.blob(objeto)
    existe=blob.exists()
    if existe:
        blob.reload()
        if (not blob.metadata or blob.metadata.get("sha256")!=sha or
                int(blob.size or 0)!=arquivo.stat().st_size):
            raise ErroGoogleCloud("objeto GCS existente nao corresponde ao hash e tamanho")
        return "EXISTENTE_CONFERIDO"
    blob.metadata={"sha256":sha,"nivon_content_addressed":"true"}
    blob.upload_from_filename(
        str(arquivo),content_type=content_type,
        if_generation_match=0,timeout=150)
    blob.reload()
    if (blob.metadata or {}).get("sha256")!=sha or int(blob.size or 0)!=arquivo.stat().st_size:
        raise ErroGoogleCloud("upload GCS nao confirmado")
    return "ENVIADO"


def executar_envio(*, base: str | Path, bucket: str, project_id: str,
                   dataset_id: str, bigquery: bool = True,
                   executar: bool = False, autorizacoes: frozenset[str] = frozenset(),
                   evidencia: str | None = None,
                   storage_client=None, bq_loader=None) -> dict:
    """GCS first, then BigQuery. Inject fake storage/client in E2E tests."""
    plano=planejar_envio(base=base,bucket=bucket,project_id=project_id,
                         dataset_id=dataset_id,bigquery=bigquery)
    if executar is not True or not _OPS.issubset(autorizacoes):
        raise PermissionError("GCP exige executar e direitos COLETA/ARMAZENAMENTO/PROCESSAMENTO")
    if not isinstance(evidencia,str) or len(evidencia.strip())<10:
        raise PermissionError("evidencia de direitos e autorizacao operacional ausente")
    if storage_client is None:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("instalar google-cloud-storage via extra gcp") from exc
        storage_client=storage.Client(project=project_id)
    remote=storage_client.bucket(bucket)
    # Bucket must already exist; never automatically provision cloud resources.
    if not remote.exists():
        raise ErroGoogleCloud("bucket GCS nao existe/acessivel")
    resultados=[]
    for item in plano["raw"]:
        estado=_enviar_unico(
            remote,arquivo=Path(item["arquivo"]),objeto=item["objeto"],
            sha=item["sha256"],content_type=item["content_type"])
        resultados.append({"dataset_id":item["dataset_id"],
                           "snapshot_id":item["snapshot_id"],"estado":estado,
                           "gcs":f'gs://{bucket}/{item["objeto"]}'})
    stage=None
    envio_bq=None
    if bigquery:
        arquivo=Path(plano["bigquery"]["arquivo"])
        stage_sha=_hash_file(arquivo)
        stage_name=f"nivon/staging/{stage_sha}.jsonl"
        stage=_enviar_unico(
            remote,arquivo=arquivo,objeto=stage_name,
            sha=stage_sha,content_type="application/x-ndjson")
        if bq_loader is None:
            from .carga_bigquery_fontes import executar_carga
            bq_loader=executar_carga
        envio_bq=bq_loader(arquivo=str(arquivo),project_id=project_id,
                          dataset_id=dataset_id,executar=True)
        if envio_bq.get("executado") is not True:
            raise ErroGoogleCloud("MERGE BigQuery nao confirmado")
    # No private URLs, content, or credentials in output.
    return {
        "estado":"GCS_E_BIGQUERY" if bigquery else "GCS_RAW_APENAS",
        "bucket":bucket,"raw_enviados":resultados,
        "staging_jsonl":stage,"bigquery":envio_bq,
        "gcs_executado":True,"bq_executado":bool(envio_bq),
        "direitos_evidencia_informada":True,
        "nao_equivale_a_publicacao_de_dados":True,
    }


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description="NIVON: envia lotes versionados para GCS/BigQuery")
    p.add_argument("--base",default="data/nivon")
    p.add_argument("--bucket",required=True)
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--sem-bigquery",action="store_true")
    p.add_argument("--executar",action="store_true")
    p.add_argument("--evidencia",default="")
    args=p.parse_args(argv)
    kwargs=dict(base=args.base,bucket=args.bucket,project_id=args.projeto,
                dataset_id=args.dataset,bigquery=not args.sem_bigquery)
    result=(executar_envio(**kwargs,executar=True,
        autorizacoes=frozenset(_OPS),evidencia=args.evidencia)
        if args.executar else planejar_envio(**kwargs))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
