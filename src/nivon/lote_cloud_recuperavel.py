"""Recuperação de lotes BigQuery a partir de GCS; extensão do núcleo canônico.

Reutiliza: arquivo_raw_gcs.arquivar_gcs, ingestao_fontes_reais.exportar_jsonl
e carga_bigquery_fontes.executar_carga. Nunca reconstrói dados sintéticos em
produção, não cria recursos de nuvem e não publica linhas em quarentena.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
from pathlib import Path

from .arquivo_raw_gcs import PREFIX, SHA, _validar_bucket
from .carga_bigquery_fontes import PROJECT, DATASET, planejar_carga, executar_carga

MAX_MANIFESTO = 1_000_000
RAW_REF = re.compile(r"^[A-Z][A-Z0-9_]{2,90}$")
VERSAO = "nivon.lote.gcs.v1"


class ErroLoteCloud(ValueError):
    pass


def _sha(path):
    hash_obj = hashlib.sha256()
    with Path(path).open("rb") as arq:
        for bloco in iter(lambda: arq.read(1024 * 1024), b""):
            hash_obj.update(bloco)
    return hash_obj.hexdigest()


def _validar_destino(*, bucket, projeto, dataset):
    _validar_bucket(bucket)
    if not isinstance(projeto, str) or not PROJECT.fullmatch(projeto):
        raise ErroLoteCloud("projeto inválido")
    if not isinstance(dataset, str) or not DATASET.fullmatch(dataset):
        raise ErroLoteCloud("dataset BigQuery inválido")


def _json_canonico(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def preparar_lote(*, banco, arquivo_jsonl, bucket, projeto, dataset):
    """Preflight OFFLINE de evidências reais: stage pertence ao SQLite e RAW."""
    _validar_destino(bucket=bucket, projeto=projeto, dataset=dataset)
    plano = planejar_carga(arquivo=arquivo_jsonl, project_id=projeto, dataset_id=dataset)
    path = Path(banco)
    if path.is_symlink() or not path.is_file():
        raise ErroLoteCloud("SQLite ausente ou symlink")
    conexao = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        snapshot_rows = conexao.execute(
            "SELECT dataset_id, snapshot_id, sha256, estado, tamanho FROM snapshots"
        ).fetchall()
        obs_rows = conexao.execute(
            "SELECT dataset_id, snapshot_id, identidade, fingerprint, referencia "
            "FROM observacoes"
        ).fetchall()
    finally:
        conexao.close()
    catalogo = {(ds, sid): (sha, estado, n)
                for ds, sid, sha, estado, n in snapshot_rows}
    observacoes = set(obs_rows)
    usados = {}
    total = 0
    with Path(arquivo_jsonl).open(encoding="utf-8") as fp:
        for linha in fp:
            row = json.loads(linha)
            chave = (row["dataset_id"], row["snapshot_id"])
            if ((row["dataset_id"], row["snapshot_id"],
                 row["identidade"], row["fingerprint"], row["referencia"])
                    not in observacoes):
                raise ErroLoteCloud("linha JSONL não pertence à observação SQLite")
            if chave not in catalogo or catalogo[chave][1] != "NORMALIZED":
                raise ErroLoteCloud("snapshot em quarentena, RAW ou ausente")
            sha, _, tamanho = catalogo[chave]
            if (not isinstance(sha, str) or not SHA.fullmatch(sha)
                    or not isinstance(tamanho, int) or tamanho <= 0
                    or not RAW_REF.fullmatch(chave[0])):
                raise ErroLoteCloud("snapshot inválido")
            usados[chave] = {"dataset_id": chave[0], "snapshot_id": chave[1],
                             "sha256": sha, "bytes": tamanho,
                             "objeto": f"{PREFIX}/{chave[0]}/{sha}.raw"}
            total += 1
    if total != plano["linhas"] or not usados:
        raise ErroLoteCloud("contagem de observações divergente")
    snapshots = sorted(usados.values(), key=lambda v: (v["dataset_id"], v["snapshot_id"]))
    stage_sha = plano["sha256"]
    stage_objeto = f"nivon/staging/v1/{stage_sha}.jsonl"
    payload = {"versao": VERSAO, "projeto": projeto, "dataset": dataset,
               "bucket": bucket, "stage_objeto": stage_objeto,
               "stage_sha256": stage_sha, "linhas": total,
               "snapshots": snapshots}
    manifesto = _json_canonico(payload)
    if len(manifesto) > MAX_MANIFESTO:
        raise ErroLoteCloud("manifesto excessivo")
    digest = hashlib.sha256(manifesto).hexdigest()
    return {"plano": payload, "manifesto_sha256": digest,
            "manifesto_objeto": f"nivon/lotes/v1/{digest}.json",
            "manifesto_bytes": manifesto, "arquivo_jsonl": str(arquivo_jsonl),
            "executado": False}


def _conferir_objeto(bucket_obj, name, sha, tamanho):
    objeto = bucket_obj.get_blob(name)
    if (objeto is None or objeto.size != tamanho
            or not isinstance(objeto.metadata, dict)
            or objeto.metadata.get("sha256") != sha):
        raise ErroLoteCloud("objeto GCS ausente ou metadados/hash divergentes")
    return objeto


def _upload_imutavel(bucket_obj, *, arquivo, nome, sha, mime):
    arquivo = Path(arquivo)
    # Revalidar os bytes no momento de envio, não apenas no planejamento.
    # Impede race entre o cálculo do manifesto e a gravação no GCS.
    if arquivo.is_symlink() or not arquivo.is_file() or _sha(arquivo) != sha:
        raise ErroLoteCloud("arquivo de stage/manifesto alterado antes do upload")
    antigo = bucket_obj.get_blob(nome)
    if antigo is not None:
        _conferir_objeto(bucket_obj, nome, sha, arquivo.stat().st_size)
        return "EXISTENTE_CONFERIDO"
    blob = bucket_obj.blob(nome)
    blob.metadata = {"sha256": sha}
    blob.upload_from_filename(str(arquivo), content_type=mime,
                              if_generation_match=0, checksum="crc32c", timeout=90)
    _conferir_objeto(bucket_obj, nome, sha, arquivo.stat().st_size)
    return "GRAVADO"


def arquivar_stage(*, banco, arquivo_jsonl, bucket, projeto, dataset,
                   executar=False, client=None):
    """Guarda JSONL e manifesto APÓS confirmar todos RAWs do arquivador canônico."""
    plano = preparar_lote(banco=banco, arquivo_jsonl=arquivo_jsonl, bucket=bucket,
                          projeto=projeto, dataset=dataset)
    if executar is not True:
        return {k: plano[k] for k in ("manifesto_sha256", "manifesto_objeto",
                                    "executado")}
    if client is None:
        from google.cloud import storage
        client = storage.Client(project=projeto)
    remoto = client.bucket(bucket)
    for item in plano["plano"]["snapshots"]:
        obj = _conferir_objeto(remoto, item["objeto"], item["sha256"], item["bytes"])
        if obj.metadata.get("snapshot_id") != item["snapshot_id"]:
            raise ErroLoteCloud("RAW GCS sem vínculo de snapshot")
    stage_sha = plano["plano"]["stage_sha256"]
    status = _upload_imutavel(remoto, arquivo=arquivo_jsonl,
                            nome=plano["plano"]["stage_objeto"],
                            sha=stage_sha, mime="application/x-ndjson")
    # O manifesto só fica disponível para replay depois da confirmação do stage.
    with tempfile.TemporaryDirectory() as tmp:
        caminho = Path(tmp) / "manifesto.json"
        caminho.write_bytes(plano["manifesto_bytes"])
        _upload_imutavel(remoto, arquivo=caminho, nome=plano["manifesto_objeto"],
                         sha=plano["manifesto_sha256"], mime="application/json")
    return {"executado": True, "stage": status, "manifesto_sha256":
            plano["manifesto_sha256"], "manifesto_gcs":
            f"gs://{bucket}/{plano['manifesto_objeto']}",
            "linhas": plano["plano"]["linhas"], "bigquery_executado": False}


def reprocessar_manifesto(*, bucket, projeto, dataset, manifesto_sha256,
                          executar=False, client=None, loader=None):
    """Replay somente com GCS imutável e MERGE existente; não reexecuta coleta."""
    _validar_destino(bucket=bucket, projeto=projeto, dataset=dataset)
    if not isinstance(manifesto_sha256, str) or not SHA.fullmatch(manifesto_sha256):
        raise ErroLoteCloud("SHA do manifesto inválido")
    if executar is not True:
        return {"manifesto_sha256": manifesto_sha256, "executado": False}
    if client is None:
        from google.cloud import storage
        client = storage.Client(project=projeto)
    remoto = client.bucket(bucket)
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        arquivo_manifesto = raiz / "manifesto.json"
        objeto_manifesto = f"nivon/lotes/v1/{manifesto_sha256}.json"
        obj = remoto.get_blob(objeto_manifesto)
        if obj is None or not 0 < obj.size <= MAX_MANIFESTO:
            raise ErroLoteCloud("manifesto não encontrado ou excessivo")
        _conferir_objeto(remoto, objeto_manifesto, manifesto_sha256, obj.size)
        obj.download_to_filename(str(arquivo_manifesto))
        if _sha(arquivo_manifesto) != manifesto_sha256:
            raise ErroLoteCloud("manifesto adulterado")
        try:
            doc = json.loads(arquivo_manifesto.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ErroLoteCloud("manifesto inválido") from exc
        if (not isinstance(doc, dict) or doc.get("versao") != VERSAO
                or doc.get("bucket") != bucket or doc.get("projeto") != projeto
                or doc.get("dataset") != dataset):
            raise ErroLoteCloud("origem/destino incompatível com manifesto")
        sha = doc.get("stage_sha256")
        if (not isinstance(sha, str) or not SHA.fullmatch(sha)
                or doc.get("stage_objeto") != f"nivon/staging/v1/{sha}.jsonl"
                or type(doc.get("linhas")) is not int
                or not 1 <= doc["linhas"] <= 150_000
                or not isinstance(doc.get("snapshots"), list)
                or not doc["snapshots"]):
            raise ErroLoteCloud("recibo de stage inválido")
        identificadores = set()
        for item in doc["snapshots"]:
            if (not isinstance(item, dict)
                    or not isinstance(item.get("dataset_id"), str)
                    or not RAW_REF.fullmatch(item["dataset_id"])
                    or not isinstance(item.get("sha256"), str)
                    or not SHA.fullmatch(item["sha256"])
                    or not isinstance(item.get("snapshot_id"), str)
                    or not SHA.fullmatch(item["snapshot_id"])
                    or item.get("objeto") !=
                       f"{PREFIX}/{item['dataset_id']}/{item['sha256']}.raw"
                    or type(item.get("bytes")) is not int
                    or item["bytes"] <= 0):
                raise ErroLoteCloud("snapshot incompatível com manifesto")
            obj_raw = _conferir_objeto(remoto,item["objeto"],
                                      item["sha256"],item["bytes"])
            if obj_raw.metadata.get("snapshot_id") != item["snapshot_id"]:
                raise ErroLoteCloud("identidade RAW divergente")
            identificadores.add((item["dataset_id"], item["snapshot_id"]))
        arq = raiz / "recuperacao.jsonl"
        obj_stage = remoto.get_blob(doc["stage_objeto"])
        if obj_stage is None:
            raise ErroLoteCloud("stage não encontrado")
        _conferir_objeto(remoto, doc["stage_objeto"], sha, obj_stage.size)
        obj_stage.download_to_filename(str(arq))
        if _sha(arq) != sha:
            raise ErroLoteCloud("stage adulterado")
        plano = planejar_carga(arquivo=arq, project_id=projeto,dataset_id=dataset)
        if plano["linhas"] != doc["linhas"] or plano["sha256"] != sha:
            raise ErroLoteCloud("stage diverge do manifesto")
        with arq.open(encoding="utf-8") as fp:
            for linha in fp:
                row = json.loads(linha)
                if (row["dataset_id"], row["snapshot_id"]) not in identificadores:
                    raise ErroLoteCloud("observação de RAW não autorizado")
        carregar = loader if loader is not None else executar_carga
        resposta = carregar(arquivo=arq, project_id=projeto,
                            dataset_id=dataset, executar=True)
        if not isinstance(resposta, dict) or resposta.get("executado") is not True:
            raise ErroLoteCloud("MERGE não confirmado")
        return {"manifesto_sha256": manifesto_sha256, "executado": True,
                "linhas": plano["linhas"], "bigquery_executado": True,
                "replay_sem_sqlite": True, "dados_publicados_externamente": False}
