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


def exportar_quarentena(*, banco, destino, fonte_dataset, snapshot_ids=None):
    """Somente QUARANTINED dos datasets permitidos, registro a registro."""
    if fonte_dataset not in FONTES:
        raise ErroStagingAgro("fonte fora da quarentena homologada")
    if snapshot_ids is not None:
        if (not isinstance(snapshot_ids,(list,tuple,frozenset))
                or not 1 <= len(snapshot_ids) <= 200
                or len(set(snapshot_ids))!=len(snapshot_ids)
                or any(not isinstance(x,str) or not SHA.fullmatch(x) for x in snapshot_ids)):
            raise ErroStagingAgro("snapshots de staging invalidos")
    path = Path(banco)
    target = Path(destino)
    if path.is_symlink() or not path.is_file() or target.is_symlink():
        raise ErroStagingAgro("base ou JSONL inválido")
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        sql="""SELECT o.dataset_id, o.snapshot_id, o.identidade,
                      o.fingerprint, s.url_publica, o.referencia,
                      o.publicacao, o.coletado_em, o.competencia,
                      o.natureza, o.unidade, o.valor, o.campos_json, s.estado
               FROM observacoes o JOIN snapshots s USING(snapshot_id)
               WHERE o.dataset_id=?"""
        parametros=[fonte_dataset]
        if snapshot_ids is not None:
            sql += " AND o.snapshot_id IN (" + ",".join("?" for _ in snapshot_ids) + ")"
            parametros.extend(snapshot_ids)
        sql += " ORDER BY o.referencia,o.identidade,o.fingerprint"
        cur=db.execute(sql,parametros)
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
            or tabela.time_partitioning.field!="data_coleta"
            or getattr(tabela,"require_partition_filter",False) is not True):
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
        parametros=[
            bigquery.ScalarQueryParameter("inicio","DATE",date.fromisoformat(plano["inicio"])),
            bigquery.ScalarQueryParameter("fim","DATE",date.fromisoformat(plano["fim"])),
        ]
        # Bloqueio de custo antes de qualquer MERGE. Dry-run retorna bytes
        # estimados e deve ser recusado se não houver estimativa confiável.
        dry_run=bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False, query_parameters=parametros)
        ensaio=cli.query(sql,job_config=dry_run)
        estimativa=getattr(ensaio,"total_bytes_processed",None)
        if type(estimativa) is not int or estimativa<0:
            raise ErroStagingAgro("dry-run sem estimativa de bytes")
        if estimativa>max_bytes_billed:
            raise ErroStagingAgro("MERGE bloqueado por limite de custo")
        cfg=bigquery.QueryJobConfig(
            maximum_bytes_billed=max_bytes_billed,
            query_parameters=parametros)
        cli.query(sql,job_config=cfg).result(timeout=150)
    finally:
        cli.delete_table(stage,not_found_ok=True)
    return {**plano, "executado":True,"linhas_enviadas":plano["linhas"],
            "estado":"BIGQUERY_STAGING_NAO_CANONICO",
            "bigquery_executado":True,"promocao_canonica":False,
            "bytes_estimados":estimativa,"limite_bytes_cobraveis":max_bytes_billed}



def reprocessar_stage_quarentena(*, sha256, fonte_dataset, bucket,
                                project_id, dataset_id, executar=False,
                                storage_client=None, bq_client=None):
    """Restaura o stage imutável do GCS e refaz MERGE sem HTTP nem SQLite.

    O id SHA do objeto GCS é obrigatório; só se aceita estágio validado
    anteriormente e QUARANTINED com referência temporal explicitamente nula.
    A identidade de WIF, as aprovações e a tabela devem existir externamente.
    """
    from .arquivo_raw_gcs import _validar_bucket
    from tempfile import TemporaryDirectory
    _destino(project_id,dataset_id)
    _validar_bucket(bucket)
    if fonte_dataset not in FONTES:
        raise ErroStagingAgro("fonte não autorizada para replay")
    if not isinstance(sha256,str) or not SHA.fullmatch(sha256):
        raise ErroStagingAgro("SHA do stage inválido")
    name=f"nivon/staging-agro-quarentena/v1/{sha256}.jsonl"
    if executar is not True:
        return {"estado":"PLANO_REPLAY_SEM_REDE",
                "fonte_dataset":fonte_dataset,"sha256":sha256,
                "gcs_objeto":name,"executado":False}
    if storage_client is None:
        from google.cloud import storage
        storage_client=storage.Client(project=project_id)
    remoto=storage_client.bucket(bucket)
    blob=remoto.get_blob(name)
    if (blob is None or type(blob.size) is not int
            or not 0 < blob.size <= MAX_BYTES
            or not isinstance(blob.metadata,dict)
            or blob.metadata.get("sha256")!=sha256):
        raise ErroStagingAgro("arquivo staging GCS ausente ou metadados inválidos")
    with TemporaryDirectory(prefix="nivon-agro-replay-") as tmp:
        destino=Path(tmp)/"stage.jsonl"
        blob.download_to_filename(str(destino))
        if destino.stat().st_size!=blob.size or _sha(destino)!=sha256:
            raise ErroStagingAgro("stage GCS adulterado; replay recusado")
        plano=verificar_jsonl(arquivo=destino,fonte_dataset=fonte_dataset,
                            projeto=project_id,dataset=dataset_id)
        if plano["sha256"]!=sha256:
            raise ErroStagingAgro("conteúdo diverge do SHA informado")
        resultado=carregar_stage(
            arquivo=destino,fonte_dataset=fonte_dataset,
            project_id=project_id,dataset_id=dataset_id,
            executar=True,client=bq_client)
        if resultado.get("bigquery_executado") is not True:
            raise ErroStagingAgro("BigQuery não confirmou MERGE")
        return {"estado":"REPLAY_STAGING_CONCLUIDO",
                "fonte_dataset":fonte_dataset,"sha256":sha256,
                "linhas":resultado["linhas"],"executado":True,
                "bigquery_executado":True,"sqlite_necessario":False,
                "http_fonte_consultado":False,"promocao_canonica":False}

def verificar_ou_criar_tabela(*, projeto, dataset, verificar=False,
                             aplicar=False, aprovado=False, client=None):
    """Bootstrap restrito a uma tabela no dataset existente, nunca ao projeto."""
    destino = _destino(projeto, dataset)
    if aplicar and (verificar is not True or aprovado is not True):
        raise PermissionError("criação de tabela staging sem aprovação")
    if verificar is not True:
        return {"destino":destino,"estado":"PLANO_SEM_REDE",
                "executado":False,"criou_tabela":False}
    try:
        from google.cloud import bigquery
        from google.api_core.exceptions import NotFound
    except ImportError as exc:
        raise RuntimeError("instalar extra nivon[gcp]") from exc
    cli=client if client is not None else bigquery.Client(project=projeto)
    ds=cli.get_dataset(f"{projeto}.{dataset}")
    if str(ds.location or "").lower() != "southamerica-east1":
        raise ErroStagingAgro("dataset fora da região NIVON")
    criou=False
    try:
        tabela=cli.get_table(destino)
    except NotFound:
        if aplicar is not True:
            return {"destino":destino,"estado":"TABELA_AUSENTE",
                    "executado":True,"criou_tabela":False}
        campos=[bigquery.SchemaField(
            nome,tipo,mode="REQUIRED" if nome in {
                "dataset_id","snapshot_id","identidade","fingerprint",
                "origem_url","referencia_tecnica","data_coleta",
                "natureza","campos","estado"} else "NULLABLE")
            for nome,tipo in TIPOS.items()]
        tabela=bigquery.Table(destino,schema=campos)
        tabela.time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,field="data_coleta")
        tabela.clustering_fields=["dataset_id","identidade","snapshot_id"]
        tabela.require_partition_filter=True
        tabela.description=(
            "NIVON staging privado: publicacoes IMEA/CONAB sem data-referencia; "
            "somente QUARANTINED, sem publicacao analitica canonica")
        cli.create_table(tabela,exists_ok=False)
        tabela=cli.get_table(destino)
        criou=True
    schema={c.name:c.field_type.upper() for c in tabela.schema}
    if (any(schema.get(k)!=t for k,t in TIPOS.items())
            or not getattr(tabela,"time_partitioning",None)
            or tabela.time_partitioning.field!="data_coleta"
            or getattr(tabela,"require_partition_filter",False) is not True
            or list(getattr(tabela,"clustering_fields",None) or [])
            != ["dataset_id","identidade","snapshot_id"]):
        raise ErroStagingAgro("tabela existente nao atende contrato staging")
    return {"destino":destino,"estado":"SCHEMA_VALIDADO",
            "executado":True,"criou_tabela":criou,
            "referencia_temporal_opcional":True,
            "promocao_canonica":False}
