"""BigQuery PRIVADO de quarentena agrícola: IMEA e CONAB, sem data referência.

Nunca utiliza carga_bigquery_fontes.nivon_observacoes nem transforma
publicacao em data_referencia. Exige tabela preexistente, GCS antes do MERGE,
identidade auditável, particionamento por data_coleta e cobrança limitada.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from .carga_bigquery_fontes import PROJECT, DATASET
from .lote_cloud_recuperavel import _upload_imutavel

FONTES = frozenset({"IMEA_PUBLICACOES_STAGING", "CONAB_SAFRAS_STAGING"})
MAX_ROWS = 75000
MAX_BYTES = 50_000_000
SHA = re.compile(r"^[0-9a-f]{64}$")
CAMPOS = (
    "dataset_id", "snapshot_id", "identidade", "fingerprint", "origem_url",
    "referencia_tecnica", "data_referencia", "data_publicacao",
    "publicacao_bruta", "data_coleta", "competencia", "natureza",
    "unidade", "valor", "campos", "estado",
)
TIPOS = {
    "dataset_id": "STRING", "snapshot_id": "STRING",
    "identidade": "STRING", "fingerprint": "STRING", "origem_url": "STRING",
    "referencia_tecnica": "STRING", "data_referencia": "DATE",
    "data_publicacao": "DATE", "publicacao_bruta": "STRING",
    "data_coleta": "TIMESTAMP", "competencia": "STRING",
    "natureza": "STRING", "unidade": "STRING", "valor": "STRING",
    "campos": "JSON", "estado": "STRING",
}


class ErroStagingAgro(ValueError):
    pass


def _destino(projeto, dataset):
    if (not isinstance(projeto, str) or not PROJECT.fullmatch(projeto)
            or not isinstance(dataset, str) or not DATASET.fullmatch(dataset)):
        raise ErroStagingAgro("projeto/dataset inválidos")
    return f"{projeto}.{dataset}.agro_publicacoes_staging"


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fp:
        for data in iter(lambda: fp.read(1024*1024), b""):
            h.update(data)
    return h.hexdigest()


def _dia_publicacao(pub):
    if pub is None:
        return None
    if not isinstance(pub, str) or len(pub) < 10:
        raise ErroStagingAgro("publicação com tipo inválido")
    try:
        day = date.fromisoformat(pub[:10])
    except ValueError as exc:
        raise ErroStagingAgro("data_publicacao inválida") from exc
    return day.isoformat()


def _dia_coleta(value):
    if not isinstance(value, str):
        raise ErroStagingAgro("data_coleta inválida")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroStagingAgro("data_coleta inválida") from exc
    if dt.utcoffset() is None:
        raise ErroStagingAgro("data_coleta sem timezone")
    return dt.astimezone(timezone.utc).date().isoformat()


def exportar_quarentena(*, banco, destino, fonte_dataset):
    """Somente QUARANTINED dos datasets permitidos, registro a registro."""
    if fonte_dataset not in FONTES:
        raise ErroStagingAgro("fonte fora da quarentena homologada")
    path = Path(banco)
    target = Path(destino)
    if path.is_symlink() or not path.is_file() or target.is_symlink():
        raise ErroStagingAgro("base ou JSONL inválido")
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        cur = db.execute(
            """SELECT o.dataset_id, o.snapshot_id, o.identidade,
                      o.fingerprint, s.url_publica, o.referencia,
                      o.publicacao, o.coletado_em, o.competencia,
                      o.natureza, o.unidade, o.valor, o.campos_json, s.estado
               FROM observacoes o JOIN snapshots s USING(snapshot_id)
               WHERE o.dataset_id=? ORDER BY o.referencia,o.identidade,o.fingerprint""",
            (fonte_dataset,))
        quantidade = 0
        inicio = fim = None
        with target.open("w",encoding="utf-8") as out:
            for row in cur:
                (ds,snapshot,identidade,fingerprint,origem,ref,pub,coleta,
                 comp,natureza,unidade,valor,campos_json,estado) = row
                if estado != "QUARANTINED":
                    raise ErroStagingAgro("snapshot promovido/normalizado inesperadamente")
                try:
                    campos = json.loads(campos_json)
                except ValueError as exc:
                    raise ErroStagingAgro("payload JSON inválido") from exc
                if (campos.get("data_referencia") is not None
                        or campos.get("tipo_referencia")
                        != "PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA"):
                    raise ErroStagingAgro("referência indevidamente inferida")
                if not SHA.fullmatch(snapshot) or not SHA.fullmatch(fingerprint):
                    raise ErroStagingAgro("SHA inválido")
                dia = _dia_coleta(coleta)
                if inicio is None or dia < inicio: inicio = dia
                if fim is None or dia > fim: fim = dia
                registro = {
                    "dataset_id": ds, "snapshot_id": snapshot,
                    "identidade": identidade, "fingerprint": fingerprint,
                    "origem_url": origem, "referencia_tecnica": ref,
                    "data_referencia": None,
                    "data_publicacao": _dia_publicacao(pub),
                    "publicacao_bruta": pub, "data_coleta": coleta,
                    "competencia": comp, "natureza": natureza,
                    "unidade": unidade, "valor": valor,
                    "campos": campos, "estado": estado,
                }
                out.write(json.dumps(registro,ensure_ascii=False,
                                     sort_keys=True,allow_nan=False)+"\n")
                quantidade += 1
                if quantidade > MAX_ROWS or out.tell() > MAX_BYTES:
                    raise ErroStagingAgro("lote staging acima do limite")
    finally:
        db.close()
    if not quantidade:
        raise ErroStagingAgro("nenhum registro de quarentena validado")
    return {"arquivo":str(target), "quantidade":quantidade,
            "fonte_dataset":fonte_dataset, "inicio":inicio, "fim":fim,
            "sha256":_sha(target), "estado":"STAGING_NAO_CANONICO",
            "bigquery_executado":False}


def verificar_jsonl(*, arquivo, fonte_dataset, projeto, dataset):
    tabela = _destino(projeto, dataset)
    if fonte_dataset not in FONTES:
        raise ErroStagingAgro("dataset não autorizado")
    path = Path(arquivo)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ErroStagingAgro("stage ausente/excessivo")
    quantidade = 0
    dias = []
    vistos = set()
    with path.open(encoding="utf-8") as fp:
        for linha in fp:
            try:
                r = json.loads(linha)
            except (ValueError,UnicodeError) as exc:
                raise ErroStagingAgro("linha inválida") from exc
            if set(r) != set(CAMPOS) or r.get("dataset_id") != fonte_dataset:
                raise ErroStagingAgro("schema/fonte divergentes")
            if r["estado"]!="QUARANTINED" or r["data_referencia"] is not None:
                raise ErroStagingAgro("promocao canonica não autorizada")
            if not isinstance(r["campos"],dict) or r["campos"].get("data_referencia") is not None:
                raise ErroStagingAgro("data_referencia inventada")
            if not all(isinstance(r[x],str) and SHA.fullmatch(r[x]) for x in ("snapshot_id","fingerprint")):
                raise ErroStagingAgro("SHA inválido")
            key = (r["dataset_id"],r["identidade"],r["fingerprint"])
            if key in vistos:
                raise ErroStagingAgro("observação duplicada no stage")
            vistos.add(key)
            dias.append(_dia_coleta(r["data_coleta"]))
            if r["data_publicacao"] is not None:
                date.fromisoformat(r["data_publicacao"])
            quantidade += 1
            if quantidade > MAX_ROWS:
                raise ErroStagingAgro("muitas linhas")
    if not quantidade:
        raise ErroStagingAgro("stage vazio")
    return {"tabela":tabela,"arquivo":str(path),"sha256":_sha(path),
            "linhas":quantidade, "fonte_dataset":fonte_dataset,
            "inicio":min(dias),"fim":max(dias),"executado":False}


def arquivar_stage_quarentena(*, arquivo, bucket, project_id, client=None):
    """JSONL content-addressed e privado no GCS; nunca publica tabela canônica."""
    from .arquivo_raw_gcs import _validar_bucket
    _validar_bucket(bucket)
    path = Path(arquivo)
    if path.is_symlink() or not path.is_file():
        raise ErroStagingAgro("JSONL ausente")
    sha = _sha(path)
    if client is None:
        from google.cloud import storage
        client = storage.Client(project=project_id)
    remoto = client.bucket(bucket)
    objeto = f"nivon/staging-agro-quarentena/v1/{sha}.jsonl"
    estado = _upload_imutavel(remoto,arquivo=path,nome=objeto,
                              sha=sha,mime="application/x-ndjson")
    return {"estado":estado,"sha256":sha,"uri":f"gs://{bucket}/{objeto}",
            "gcs_executado":True,"bigquery_executado":False}


def carregar_stage(*, arquivo, fonte_dataset, project_id, dataset_id,
                   executar=False, client=None, max_bytes_billed=100_000_000):
    """MERGE somente tabela agro_publicacoes_staging já existente e particionada."""
    plano = verificar_jsonl(arquivo=arquivo, fonte_dataset=fonte_dataset,
                             projeto=project_id,dataset=dataset_id)
    if executar is not True:
        raise PermissionError("STAGING_BIGQUERY_OFF")
    if (type(max_bytes_billed) is not int or
            not 1_000_000 <= max_bytes_billed <= 100_000_000):
        raise ErroStagingAgro("limite de cobrança inválido")
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError("instalar extra nivon[gcp]") from exc
    cli = client if client is not None else bigquery.Client(project=project_id)
    cli.get_dataset(f"{project_id}.{dataset_id}")
    tabela = cli.get_table(plano["tabela"])
    schema={col.name:col.field_type.upper() for col in tabela.schema}
    if (any(schema.get(k)!=tipo for k,tipo in TIPOS.items())
            or not getattr(tabela,"time_partitioning",None)
            or tabela.time_partitioning.field!="data_coleta"):
        raise ErroStagingAgro("schema/particionamento staging incompatível")
    stage=f"{project_id}.{dataset_id}._agro_stage_{uuid4().hex[:22]}"
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=[bigquery.SchemaField(k,t) for k,t in TIPOS.items()],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
    try:
        with open(arquivo,"rb") as fp:
            cli.load_table_from_file(fp,stage,job_config=config).result(timeout=150)
        chaves=("dataset_id","identidade","fingerprint")
        on=" AND ".join(f"T.{k}=S.{k}" for k in chaves)
        colunas=", ".join(CAMPOS)
        valores=", ".join("S."+k for k in CAMPOS)
        sql=(f"MERGE `{plano['tabela']}` T USING `{stage}` S "
             f"ON {on} AND DATE(T.data_coleta) BETWEEN @inicio AND @fim "
             f"WHEN NOT MATCHED THEN INSERT ({colunas}) VALUES ({valores})")
        cfg=bigquery.QueryJobConfig(
            maximum_bytes_billed=max_bytes_billed,
            query_parameters=[
                bigquery.ScalarQueryParameter("inicio","DATE",date.fromisoformat(plano["inicio"])),
                bigquery.ScalarQueryParameter("fim","DATE",date.fromisoformat(plano["fim"])),
            ])
        cli.query(sql,job_config=cfg).result(timeout=150)
    finally:
        cli.delete_table(stage,not_found_ok=True)
    return {**plano, "executado":True,"linhas_enviadas":plano["linhas"],
            "estado":"BIGQUERY_STAGING_NAO_CANONICO",
            "bigquery_executado":True,"promocao_canonica":False}
