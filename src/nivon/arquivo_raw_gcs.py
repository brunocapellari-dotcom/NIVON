"""NIVON: arquivo bruto permanente, imutável, com verificação de integridade no GCS.

Somente processo opt-in autenticado externamente por Workload Identity / ADC.
Carrega snapshots previamente registrados no ledger SQLite; proíbe upload de
arquivos que não estejam na árvore RAW permitida e não aceita URLs externas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
DATASET = re.compile(r"^[A-Z][A-Z0-9_]{2,90}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_OBJECTS = 200
MAX_BYTES = 25_000_000
PREFIX = "nivon/raw/v1"


class ErroArquivoCloud(ValueError):
    pass


def _validar_bucket(nome):
    if (not isinstance(nome, str) or not BUCKET.fullmatch(nome)
            or ".." in nome or nome.startswith("goog")):
        raise ErroArquivoCloud("bucket GCS fora do formato")
    return nome


def preparar_manifesto(*, banco, raw_dir, bucket, limite=MAX_OBJECTS,
                       fonte_dataset=None):
    """Valida todos os objetos sem abrir cliente Google nem conexão de rede."""
    _validar_bucket(bucket)
    if fonte_dataset is not None and (not isinstance(fonte_dataset,str)
                                      or not DATASET.fullmatch(fonte_dataset)):
        raise ErroArquivoCloud("fonte_dataset inválido")
    if type(limite) is not int or not 1 <= limite <= MAX_OBJECTS:
        raise ErroArquivoCloud("limite de objetos invalido")
    path = Path(banco)
    root = Path(raw_dir)
    if path.is_symlink() or not path.is_file() or root.is_symlink() or not root.is_dir():
        raise ErroArquivoCloud("SQLite/RAW inexistente ou symlink")
    base = root.resolve(strict=True)
    db = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        registros = db.execute("""SELECT dataset_id, snapshot_id, sha256, coletado_em,
                         content_type, tamanho, arquivo, url_publica FROM snapshots
                         WHERE (? IS NULL OR dataset_id=?)
                         ORDER BY dataset_id, sha256""",
                         (fonte_dataset,fonte_dataset)).fetchall()
    finally:
        db.close()
    if not registros or len(registros) > limite:
        raise ErroArquivoCloud("manifesto vazio ou acima do limite")
    itens = []
    for ds, sid, sha, dt, mime, tamanho, arq, uri in registros:
        if (not isinstance(ds, str) or not DATASET.fullmatch(ds) or
                not all(isinstance(v,str) and SHA.fullmatch(v) for v in (sid, sha))):
            raise ErroArquivoCloud("identidade de snapshot invalida")
        nome = Path(arq)
        if nome.is_symlink() or not nome.is_file():
            raise ErroArquivoCloud("RAW ausente ou symlink")
        resolved = nome.resolve(strict=True)
        if resolved.parent != base / ds or resolved.name != sha + ".raw":
            raise ErroArquivoCloud("caminho RAW difere do hash/dataset")
        if type(tamanho) is not int or not 1 <= tamanho <= MAX_BYTES or resolved.stat().st_size != tamanho:
            raise ErroArquivoCloud("tamanho de RAW invalido")
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if digest != sha:
            raise ErroArquivoCloud("arquivo RAW alterado/corrompido")
        if (not isinstance(uri,str) or not uri.startswith("https://") or
                any(x in uri for x in ("@", "#", "\r", "\n"))):
            raise ErroArquivoCloud("origem do snapshot invalida")
        if not isinstance(dt,str) or len(dt)>45:
            raise ErroArquivoCloud("timestamp de coleta invalido")
        if mime not in ("text/csv","application/json","application/octet-stream","application/vnd.ms-excel"):
            raise ErroArquivoCloud("MIME de arquivo invalido")
        itens.append({
            "dataset": ds, "snapshot_id": sid, "sha256": sha,
            "coletado_em": dt, "content_type": mime,
            "bytes": tamanho, "arquivo_local": str(resolved),
            "origem": uri,
            "objeto": f"{PREFIX}/{ds}/{sha}.raw",
        })
    return {"bucket":bucket, "objetos":itens, "quantidade":len(itens),
            "bytes_total":sum(x["bytes"] for x in itens), "executado":False}


def arquivar_gcs(*, banco, raw_dir, bucket, executar=False, client=None,
                 fonte_dataset=None):
    manifest = preparar_manifesto(banco=banco, raw_dir=raw_dir, bucket=bucket,
                                   fonte_dataset=fonte_dataset)
    if executar is not True:
        raise PermissionError("UPLOAD_GCS_RAW_OFF")
    if client is None:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("instale o extra nivon[gcp] para armazenamento") from exc
        client = storage.Client()
    recipiente = client.bucket(bucket)
    novos = 0
    ja_existiam = 0
    for item in manifest["objetos"]:
        blob = recipiente.blob(item["objeto"])
        esperado = {"sha256":item["sha256"],"snapshot_id":item["snapshot_id"],
                    "dataset_id":item["dataset"],"coletado_em":item["coletado_em"],
                    "origem":item["origem"]}
        existe = recipiente.get_blob(item["objeto"])
        if existe is not None:
            if (existe.size != item["bytes"] or not isinstance(existe.metadata,dict) or
                    existe.metadata.get("sha256") != item["sha256"] or
                    existe.metadata.get("snapshot_id") != item["snapshot_id"]):
                raise ErroArquivoCloud("objeto existente diverge do SHA/tamanho")
            ja_existiam += 1
            continue
        blob.metadata = esperado
        try:
            blob.upload_from_filename(item["arquivo_local"],
                content_type=item["content_type"], if_generation_match=0,
                checksum="crc32c", timeout=90)
            novos += 1
        except Exception as exc:
            # Uma corrida de uploads simultâneos deve continuar fail-closed,
            # não substituir um RAW que possa ter sido criado por terceiro.
            raise ErroArquivoCloud(
                "falha GCS ao gravar RAW imutavel; verificar permisos/custo/rede"
            ) from exc
    return {"bucket":bucket,"objetos_verificados":manifest["quantidade"],
            "novos":novos,"ja_existiam":ja_existiam,
            "bytes_totais":manifest["bytes_total"],
            "armazenamento":"GCS_RAW_SHA256","executado":True,
            "bigquery_executado":False}


def main(argv=None):
    p=argparse.ArgumentParser(description="Arquivar RAW do NIVON no GCS (opt-in)")
    p.add_argument("--banco", required=True)
    p.add_argument("--raw-dir", required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    if args.executar:
        output=arquivar_gcs(banco=args.banco,raw_dir=args.raw_dir,bucket=args.bucket,
                           executar=True)
    else:
        output=preparar_manifesto(banco=args.banco,raw_dir=args.raw_dir,bucket=args.bucket)
        output={"bucket":output["bucket"],
                "quantidade":output["quantidade"],
                "bytes_total":output["bytes_total"],
                "executado":False}
    print(json.dumps(output,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
