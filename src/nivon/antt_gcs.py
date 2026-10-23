"""Arquivamento de arquivos ANTT/SIADE em Google Cloud Storage sob opt-in.

A operacao exige bucket previamente configurado. Nunca cria bucket,
nao modifica objeto ja publicado e nao grava credenciais no codigo.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

from .transporte_multimodal import ErroTransporte

_BUCKET = re.compile(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]\Z")


def nome_objeto(ano: int, sha256: str) -> str:
    if type(ano) is not int or not 2006 <= ano <= 2100 or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ErroTransporte("identificador de snapshot ANTT invalido")
    return f"nivon/fontes/antt/ferrovia/ano={ano}/sha256={sha256}.csv"


def plano_gcs(pasta: str | Path, anos: list[int], bucket: str) -> list[tuple[bytes, dict]]:
    if not _BUCKET.fullmatch(bucket) or ".." in bucket:
        raise ErroTransporte("bucket GCS invalido")
    if len(anos) != len(set(anos)) or not anos:
        raise ErroTransporte("anos ausentes ou duplicados")
    p = Path(pasta)
    try:
        manifest = json.loads((p / "manifesto-antt.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ErroTransporte("manifesto nao encontrado ou invalido") from None
    if manifest.get("formato") != "nivon-antt-staging-v1":
        raise ErroTransporte("manifesto de fontes inesperado")
    out = []
    for ano in sorted(anos):
        registro = manifest.get("anos", {}).get(str(ano))
        if not isinstance(registro, dict) or registro.get("status") != "STAGING_NAO_HOMOLOGADO":
            raise ErroTransporte("snapshot nao homologado em staging")
        data = (p / f"antt-od-{ano}.csv").read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if not data or len(data) > 16_000_000 or sha != registro.get("sha256"):
            raise ErroTransporte("arquivo bruto invalido ou SHA nao confere")
        key = nome_objeto(ano, sha)
        out.append((data, {"ano": ano, "sha256": sha,
                           "objeto": key, "gcs_uri": f"gs://{bucket}/{key}",
                           "bytes": len(data), "url_fonte": registro["url"],
                           "verificado_em": registro["verificado_utc"]}))
    return out


def arquivar_gcs(pasta: str | Path, anos: list[int], bucket: str, *,
                 habilitar_escrita=False, cliente=None, precondition_error=None) -> list[dict]:
    planos = plano_gcs(pasta, anos, bucket)
    if not habilitar_escrita:
        return [{"estado": "DRY_RUN", **info} for _, info in planos]
    if cliente is None:
        try:
            from google.cloud import storage
            from google.api_core.exceptions import PreconditionFailed
        except ImportError:
            raise ErroTransporte("google-cloud-storage nao instalado") from None
        cliente = storage.Client()
        precondition_error = PreconditionFailed
    if precondition_error is None:
        raise ErroTransporte("tratamento de precondicao GCS nao configurado")
    b = cliente.bucket(bucket)
    if not b.exists(client=cliente):
        raise ErroTransporte("bucket GCS inexistente (criacao nao automatica)")
    resultados = []
    for payload, meta in planos:
        blob = b.blob(meta["objeto"])
        blob.metadata = {
            "fonte": "ANTT_SIADE_ORIGEM_DESTINO",
            "sha256": meta["sha256"],
            "ano": str(meta["ano"]),
            "url_fonte": meta["url_fonte"],
            "data_coleta": meta["verificado_em"],
            "estado": "STAGING_NAO_HOMOLOGADO",
        }
        try:
            blob.upload_from_string(payload, content_type="text/csv",
                                    if_generation_match=0, timeout=60)
            status = "ARQUIVADO"
        except precondition_error:
            # Objeto no mesmo path so pode ser reutilizado se checksum identico.
            blob.reload(client=cliente)
            if not blob.metadata or blob.metadata.get("sha256") != meta["sha256"]:
                raise ErroTransporte("objeto ja existe com metadados diferentes")
            status = "JA_ARQUIVADO"
        resultados.append({"estado": status, **meta})
    return resultados


def main():
    parser = argparse.ArgumentParser(description="NIVON: arquivamento bruto ANTT em GCS")
    parser.add_argument("--staging", required=True)
    parser.add_argument("--anos", nargs="+", type=int, required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--live", action="store_true")
    a = parser.parse_args()
    try:
        r = arquivar_gcs(a.staging, a.anos, a.bucket, habilitar_escrita=a.live)
    except (ErroTransporte, OSError) as exc:
        print(json.dumps({"estado": "BLOQUEADO", "motivo": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"arquivo": "ANTT_SIADE", "resultados": r}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
