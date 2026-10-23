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
import tempfile
from urllib.parse import urlsplit,parse_qs
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
_MAX_SICARM = 120_000_000


class ErroGoogleCloud(ValueError):
    pass


def _hash_file(file: Path) -> str:
    h = hashlib.sha256()
    with file.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def _pack(banco: Path, raw_dir: Path, fonte_dataset: str | None = None) -> list[dict]:
    if banco.is_symlink() or not banco.is_file() or raw_dir.is_symlink() or not raw_dir.is_dir():
        raise ErroGoogleCloud("SQLite ou diretorio RAW ausente/symlink")
    if fonte_dataset is not None and (not isinstance(fonte_dataset, str) or not _ID.fullmatch(fonte_dataset)):
        raise ErroGoogleCloud("fonte_dataset invalido")
    db = sqlite3.connect(str(banco))
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            """SELECT dataset_id,sha256,snapshot_id,estado,arquivo,
                      tamanho,content_type,coletado_em,url_publica
                 FROM snapshots WHERE (? IS NULL OR dataset_id=?)
                 ORDER BY dataset_id,sha256""", (fonte_dataset, fonte_dataset)
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
        limite = _MAX_SICARM if ds=="CONAB_ARMAZENS_CAPACIDADE" else _MAX_RAW
        if not 0<n<=limite or n!=row["tamanho"] or _hash_file(arquivo)!=sha:
            raise ErroGoogleCloud("RAW alterado/perdido ou excedeu limite")
        uri=urlsplit(row["url_publica"])
        secret_keys={"token","key","api_key","password","secret","access_token","signature"}
        if (uri.scheme!="https" or not uri.hostname or uri.username or uri.password
                or uri.fragment or secret_keys.intersection(k.lower() for k in parse_qs(uri.query))):
            raise ErroGoogleCloud("origem RAW nao auditavel ou possui segredo na URL")
        if (ds,sha) in vistos:
            raise ErroGoogleCloud("snapshot duplicado")
        vistos.add((ds,sha))
        items.append({
            "dataset_id":ds,"sha256":sha,"snapshot_id":snapshot,
            "estado":estado,"arquivo":str(arquivo),"bytes":n,
            "content_type":row["content_type"],
            "coletado_em":row["coletado_em"],
            "origem_url":row["url_publica"],
            "objeto":f"nivon/raw/{ds}/{sha}.raw",
        })
    return items


def planejar_envio(*, base: str | Path, bucket: str, project_id: str,
                   dataset_id: str, bigquery: bool = True,
                   fonte_dataset: str | None = None) -> dict:
    """Preflight offline; will not touch storage, HTTP or BigQuery."""
    if not isinstance(bucket,str) or not _BUCKET.fullmatch(bucket):
        raise ErroGoogleCloud("bucket GCS invalido")
    pasta=Path(base)
    items=_pack(pasta/"fontes_reais.sqlite",pasta/"raw",fonte_dataset)
    estados=sorted(set(item["estado"] for item in items))
    if bigquery and estados!=["NORMALIZED"]:
        raise ErroGoogleCloud("BigQuery bloqueado: lote contem RAW ou QUARENTENA")
    from .carga_bigquery_fontes import PROJECT, DATASET
    if not PROJECT.fullmatch(project_id) or not DATASET.fullmatch(dataset_id):
        raise ErroGoogleCloud("project_id/dataset BigQuery invalidos")
    path = pasta/("staging_fontes_reais" + ("_" + fonte_dataset if fonte_dataset else "") + ".jsonl")
    if bigquery:
        exportar_jsonl(banco=pasta/"fontes_reais.sqlite",destino=path,
                       dataset_id=fonte_dataset)
        bq=planejar_carga(arquivo=path,project_id=project_id,dataset_id=dataset_id)
        # Exported JSONL must have observations for all valid source snapshots.
        if bq["linhas"]<1:
            raise ErroGoogleCloud("sem observacoes")
    else:
        bq=None
    return {
        "estado":"PREFLIGHT_OK","bucket":bucket,"project_id":project_id,
        "dataset_id":dataset_id,"fonte_dataset":fonte_dataset,
        "raw":items, "origem_sqlite":str(pasta/"fontes_reais.sqlite"),
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
                   storage_client=None, bq_loader=None,
                   fonte_dataset: str | None = None) -> dict:
    """GCS first, then BigQuery. Inject fake storage/client in E2E tests."""
    plano=planejar_envio(base=base,bucket=bucket,project_id=project_id,
                         dataset_id=dataset_id,bigquery=bigquery,
                         fonte_dataset=fonte_dataset)
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
    # Proveniencia persiste no GCS mesmo quando o SQLite local e efemero.
    # O manifesto e content-addressed, reproduzivel e armazenado no bucket privado.
    manifest_items=[{k:v for k,v in item.items() if k!="arquivo"} for item in plano["raw"]]
    documento={"schema_version":"1.1.0","fontes":manifest_items}
    if bigquery:
        arquivo_stage=Path(plano["bigquery"]["arquivo"])
        sha_stage=_hash_file(arquivo_stage)
        documento["carga_bigquery"]={
            "staging_objeto":f"nivon/staging/{sha_stage}.jsonl",
            "sha256":sha_stage,
            "project_id":project_id,"dataset_id":dataset_id,
            "linhas":plano["bigquery"]["linhas"],
        }
    manifest_bytes=(json.dumps(
        documento,ensure_ascii=False,sort_keys=True,
        separators=(",",":"))+"\n").encode("utf-8")
    manifest_sha=hashlib.sha256(manifest_bytes).hexdigest()
    manifest_name=f"nivon/manifests/{manifest_sha}.json"
    with tempfile.TemporaryDirectory() as temp_dir:
        manifest_file=Path(temp_dir)/"manifest.json"
        manifest_file.write_bytes(manifest_bytes)
        manifest_status=_enviar_unico(
            remote,arquivo=manifest_file,objeto=manifest_name,sha=manifest_sha,
            content_type="application/json")
    stage=None
    envio_bq=None
    if bigquery:
        arquivo=arquivo_stage
        stage_sha=sha_stage
        stage_name=documento["carga_bigquery"]["staging_objeto"]
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
        "manifesto_gcs":f"gs://{bucket}/{manifest_name}",
        "manifesto_status":manifest_status,
        "staging_jsonl":stage,"bigquery":envio_bq,
        "gcs_executado":True,"bq_executado":bool(envio_bq),
        "direitos_evidencia_informada":True,
        "nao_equivale_a_publicacao_de_dados":True,
    }



def reprocessar_bigquery_do_manifesto(*, bucket: str, manifesto_sha256: str,
                                      project_id: str, dataset_id: str,
                                      executar: bool = False,
                                      autorizacoes: frozenset[str] = frozenset(),
                                      evidencia: str | None = None,
                                      storage_client=None, bq_loader=None) -> dict:
    """Recupera stage GCS após falha no MERGE, mesmo sem SQLite/runner original.

    Somente manifesto content-addressed desta ponte e destino original exato.
    Não reexecuta HTTP, não provisiona GCP e jamais promove quarentena.
    """
    from .carga_bigquery_fontes import PROJECT, DATASET, MAX_BYTES, planejar_carga

    if (not isinstance(bucket, str) or not _BUCKET.fullmatch(bucket)
            or not isinstance(manifesto_sha256, str)
            or not _SHA.fullmatch(manifesto_sha256)
            or not isinstance(project_id, str) or not PROJECT.fullmatch(project_id)
            or not isinstance(dataset_id, str) or not DATASET.fullmatch(dataset_id)):
        raise ErroGoogleCloud("identificadores de recuperação inválidos")
    if executar is not True or not _OPS.issubset(autorizacoes):
        raise PermissionError("recuperacao Google Cloud não autorizada")
    if not isinstance(evidencia, str) or len(evidencia.strip()) < 10:
        raise PermissionError("evidencia de direitos ausente")
    if storage_client is None:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("instalar extra gcp") from exc
        storage_client=storage.Client(project=project_id)
    remote=storage_client.bucket(bucket)
    if not remote.exists():
        raise ErroGoogleCloud("bucket inexistente ou inacessível")

    def baixar_verificado(nome: str, sha: str, destino: Path, limite: int) -> None:
        blob=remote.blob(nome)
        if not blob.exists():
            raise ErroGoogleCloud("objeto de replay ausente")
        blob.reload()
        n=int(blob.size or 0)
        if (not blob.metadata or blob.metadata.get("sha256")!=sha
                or not 0 < n <= limite):
            raise ErroGoogleCloud("metadados de replay divergentes")
        blob.download_to_filename(str(destino))
        if destino.stat().st_size!=n or _hash_file(destino)!=sha:
            raise ErroGoogleCloud("hash de replay diferente do manifesto")

    with tempfile.TemporaryDirectory() as tmp:
        raiz=Path(tmp)
        nome_manifesto=f"nivon/manifests/{manifesto_sha256}.json"
        arquivo_manifesto=raiz/"manifesto.json"
        baixar_verificado(nome_manifesto,manifesto_sha256,arquivo_manifesto,1_000_000)
        try:
            documento=json.loads(arquivo_manifesto.read_text(encoding="utf-8"))
        except (UnicodeError,ValueError) as exc:
            raise ErroGoogleCloud("manifesto inválido") from exc
        if (not isinstance(documento,dict) or documento.get("schema_version")!="1.1.0"
                or not isinstance(documento.get("fontes"),list)
                or not documento["fontes"]):
            raise ErroGoogleCloud("manifesto sem fontes válidas")
        carga=documento.get("carga_bigquery")
        if not isinstance(carga,dict):
            raise ErroGoogleCloud("manifesto sem carga normalizada; quarentena bloqueada")
        sha=carga.get("sha256")
        if (not isinstance(sha,str) or not _SHA.fullmatch(sha)
                or carga.get("staging_objeto")!=f"nivon/staging/{sha}.jsonl"
                or carga.get("project_id")!=project_id
                or carga.get("dataset_id")!=dataset_id
                or type(carga.get("linhas")) is not int
                or not 1 <= carga["linhas"] <= 75000):
            raise ErroGoogleCloud("destino ou identidade de stage divergente")
        identidades=set()
        for item in documento["fontes"]:
            if (not isinstance(item,dict) or item.get("estado")!="NORMALIZED"
                    or not isinstance(item.get("dataset_id"),str)
                    or not _ID.fullmatch(item["dataset_id"])
                    or not isinstance(item.get("snapshot_id"),str)
                    or not _SHA.fullmatch(item["snapshot_id"])):
                raise ErroGoogleCloud("RAW não normalizado no manifesto de replay")
            identidades.add((item["dataset_id"],item["snapshot_id"]))
        stage=raiz/"recuperacao.jsonl"
        baixar_verificado(carga["staging_objeto"],sha,stage,MAX_BYTES)
        plano=planejar_carga(arquivo=stage,project_id=project_id,dataset_id=dataset_id)
        if plano["sha256"]!=sha or plano["linhas"]!=carga["linhas"]:
            raise ErroGoogleCloud("stage divergente do recibo de recuperação")
        with stage.open(encoding="utf-8") as fp:
            for linha in fp:
                obs=json.loads(linha)
                if (obs["dataset_id"],obs["snapshot_id"]) not in identidades:
                    raise ErroGoogleCloud("stage contém snapshot fora do manifesto")
        if bq_loader is None:
            from .carga_bigquery_fontes import executar_carga
            bq_loader=executar_carga
        resultado=bq_loader(arquivo=str(stage),project_id=project_id,
                            dataset_id=dataset_id,executar=True)
        if not isinstance(resultado,dict) or resultado.get("executado") is not True:
            raise ErroGoogleCloud("reprocessamento BigQuery não confirmado")
        return {"estado":"BIGQUERY_RECUPERADO","manifesto_sha256":manifesto_sha256,
                "linhas":plano["linhas"],"bucket":bucket,
                "bq_executado":True,"publicacao_automatica":False}


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
