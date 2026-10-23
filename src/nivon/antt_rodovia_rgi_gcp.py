"""Carga única ANTT Rodoviário TRC 2025, top 16 fluxos RGI, no GCS e BigQuery.

Produto desconhecido, tabela parcial, sem inferência de transbordos ou frete.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json
from pathlib import Path
from .antt_anuario_rgi import PDF_URL, PDF_LIMIT, baixar_pdf, texto_pdf, extrair_tabela_12

PROJECT, DATASET, BUCKET = "nivon-data", "nivon_raw", "nivon-data-raw-2026"
TABLE = "antt_rodovia_rgi_top16_snapshots"
VIEW = "vw_antt_rodovia_rgi_top16_atual"
MAX_QUERY_BYTES = 60_000_000

class ErroRGIGCP(ValueError): pass

FIELDS = {
    "sha256":"STRING", "ano":"INTEGER", "origem_uf":"STRING",
    "origem_rgi":"STRING", "destino_uf":"STRING", "destino_rgi":"STRING",
    "toneladas":"INTEGER", "participacao_pct":"NUMERIC",
    "data_referencia":"DATE", "competencia":"STRING",
    "data_publicacao":"DATE", "data_coleta":"TIMESTAMP",
    "fonte":"STRING", "classificacao":"STRING",
    "escopo":"STRING", "granularidade":"STRING",
}

def preparar_documento(pdf: bytes, *, data_coleta: datetime):
    if not isinstance(pdf,bytes) or not 100<len(pdf)<=PDF_LIMIT or not pdf.startswith(b"%PDF-"):
        raise ErroRGIGCP("PDF oficial nao reconhecido")
    if not isinstance(data_coleta,datetime) or data_coleta.utcoffset() is None:
        raise ErroRGIGCP("data_coleta sem fuso")
    base=extrair_tabela_12(texto_pdf(pdf))
    if len(base)!=16 or len({
        (x["origem_uf"],x["origem_rgi"],x["destino_uf"],x["destino_rgi"]) for x in base
    })!=16:
        raise ErroRGIGCP("RGI top16 incompleto ou duplicado")
    digest=sha256(pdf).hexdigest()
    rows=[]
    for x in base:
        if (x["ano"]!=2025 or x["escopo"]!="TOP_16_FLUXOS_GERAIS_ANUAIS"
                or x["produto"] is not None or x["ncm"] is not None
                or type(x["toneladas"]) is not int or x["toneladas"]<=0):
            raise ErroRGIGCP("schema RGI nao homologado ou produto inventado")
        row={
            "sha256":digest, "ano":2025,
            "origem_uf":x["origem_uf"],"origem_rgi":x["origem_rgi"],
            "destino_uf":x["destino_uf"],"destino_rgi":x["destino_rgi"],
            "toneladas":x["toneladas"],"participacao_pct":x["participacao_pct"],
            "data_referencia":"2025-12-31","competencia":"2025",
            "data_publicacao":None,
            "data_coleta":data_coleta.astimezone(timezone.utc).isoformat(),
            "fonte":PDF_URL,"classificacao":"OBSERVADO_RELATORIO_OFICIAL_TOP16",
            "escopo":"TOP_16_FLUXOS_GERAIS_ANUAIS","granularidade":"RGI",
        }
        if set(row)!=set(FIELDS): raise ErroRGIGCP("colunas divergentes")
        rows.append(row)
    return rows,{"sha256":digest,"bytes_pdf":len(pdf),"linhas":16,
                 "toneladas_top16":str(sum(x["toneladas"] for x in rows)),
                 "ano":2025,"universo_nacional":False,"produto_identificado":False}

def sql_view_atual():
    q=chr(96)
    src=f"{PROJECT}.{DATASET}.{TABLE}"
    view=f"{PROJECT}.{DATASET}.{VIEW}"
    return (f"CREATE OR REPLACE VIEW {q}{view}{q} AS "
            "SELECT * EXCEPT(rn) FROM (SELECT *, ROW_NUMBER() OVER "
            "(PARTITION BY ano,origem_uf,origem_rgi,destino_uf,destino_rgi "
            f"ORDER BY data_coleta DESC,sha256 DESC) rn FROM {q}{src}{q}) WHERE rn=1")

def arquivar(pdf, plano, *, storage_client=None, precondition_error=None):
    if storage_client is None:
        from google.cloud import storage
        from google.api_core.exceptions import PreconditionFailed
        storage_client=storage.Client(project=PROJECT)
        precondition_error=PreconditionFailed
    if precondition_error is None: raise ErroRGIGCP("precondicao GCS ausente")
    bucket=storage_client.bucket(BUCKET)
    if not bucket.exists(client=storage_client):
        raise ErroRGIGCP("bucket existente nao encontrado")
    nome=f"nivon/fontes/antt/rodovia/anuario-trc-2025/sha256={plano['sha256']}.pdf"
    blob=bucket.blob(nome)
    blob.metadata={"fonte":"ANTT_ANUARIO_TRC_2025","sha256":plano["sha256"],
                   "url_fonte":PDF_URL,"natureza":"ARQUIVO_PUBLICO_OFICIAL"}
    try:
        blob.upload_from_string(pdf,content_type="application/pdf",if_generation_match=0,timeout=90)
        estado="ARQUIVADO"
    except precondition_error:
        blob.reload(client=storage_client)
        if not blob.metadata or blob.metadata.get("sha256")!=plano["sha256"]:
            raise ErroRGIGCP("objeto com SHA divergente")
        estado="JA_ARQUIVADO"
    return {"estado":estado,"sha256":plano["sha256"],"uri":f"gs://{BUCKET}/{nome}"}

def carregar(pdf, *, data_coleta, cliente_bq=None, sdk=None, arquivador=arquivar):
    rows,plano=preparar_documento(pdf,data_coleta=data_coleta)
    if cliente_bq is None:
        from google.cloud import bigquery as sdk
        cliente_bq=sdk.Client(project=PROJECT)
    elif sdk is None:
        raise ErroRGIGCP("SDK de teste ausente")
    ref=f"{PROJECT}.{DATASET}.{TABLE}"
    cliente_bq.get_dataset(f"{PROJECT}.{DATASET}")
    not_found=getattr(sdk, "NotFound", None)
    if not_found is None:
        from google.api_core.exceptions import NotFound as not_found
    try: tabela=cliente_bq.get_table(ref)
    except not_found:
        tabela=sdk.Table(ref,schema=[sdk.SchemaField(k,v) for k,v in FIELDS.items()])
        tabela.time_partitioning=sdk.TimePartitioning(type_=sdk.TimePartitioningType.DAY,field="data_referencia")
        tabela.clustering_fields=["origem_uf","destino_uf","origem_rgi","destino_rgi"]
        tabela=cliente_bq.create_table(tabela)
    if (not tabela.time_partitioning or tabela.time_partitioning.field!="data_referencia"
            or {f.name:f.field_type for f in tabela.schema}!=FIELDS):
        raise ErroRGIGCP("tabela BigQuery preexistente com schema errado")
    q=chr(96)
    sql=(f"SELECT COUNT(*) AS n, SUM(toneladas) AS tu FROM {q}{ref}{q} "
         "WHERE data_referencia=DATE '2025-12-31' AND ano=@ano AND sha256=@sha")
    cfg=sdk.QueryJobConfig(maximum_bytes_billed=MAX_QUERY_BYTES,query_parameters=[
        sdk.ScalarQueryParameter("ano","INT64",2025),
        sdk.ScalarQueryParameter("sha","STRING",plano["sha256"])])
    def conferir():
        result=list(cliente_bq.query(sql,job_config=cfg).result(timeout=90))
        if len(result)!=1: raise ErroRGIGCP("BQ retornou contagens invalidas")
        val=(int(result[0].n),int(result[0].tu or 0))
        if val not in ((0,0),(16,int(plano["toneladas_top16"]))):
            raise ErroRGIGCP("snapshot BQ parcial ou divergente")
        return val
    antes=conferir()
    obj=arquivador(pdf,plano)
    if obj["estado"] not in ("ARQUIVADO","JA_ARQUIVADO") or obj["sha256"]!=plano["sha256"]:
        raise ErroRGIGCP("GCS nao validado")
    if antes[0]==0:
        conf=sdk.LoadJobConfig(
            schema=[sdk.SchemaField(k,v) for k,v in FIELDS.items()],
            source_format=sdk.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=sdk.WriteDisposition.WRITE_APPEND,max_bad_records=0)
        job=cliente_bq.load_table_from_json(
            rows,ref,job_config=conf,
            job_id=f"nivon_antt_rodovia_rgi_2025_{plano['sha256'][:24]}")
        job.result(timeout=240)
        if job.errors: raise ErroRGIGCP("job BQ retornou erros")
        status="CARREGADO"
    else: status="SEM_MUDANCA"
    if conferir()!=(16,int(plano["toneladas_top16"])):
        raise ErroRGIGCP("pos-carga diverge da tabela oficial")
    cliente_bq.query(sql_view_atual(),job_config=sdk.QueryJobConfig(maximum_bytes_billed=MAX_QUERY_BYTES)).result(timeout=90)
    return {"estado":"ANTT_RGI_TOP16_2025_CONCILIADO","ano":2025,
            "fonte_url":PDF_URL,"sha256_pdf":plano["sha256"],
            "bytes_pdf":plano["bytes_pdf"],"registros":16,
            "toneladas_top16":plano["toneladas_top16"],
            "bq_tabela":ref,"bq_view":f"{PROJECT}.{DATASET}.{VIEW}",
            "gcs_uri":obj["uri"],"gcs_estado":obj["estado"],"bq_estado":status,
            "granularidade":"RGI","escopo":"TOP_16_FLUXOS_GERAIS_ANUAIS",
            "produto_identificado":False,"transbordo_confirmado":False,
            "somar_com_ferrovia_ou_hidrovia":False,
            "carga_recorrente_ativada":False}

def main(argv=None):
    p=argparse.ArgumentParser(description="ANTT TRC top16 RGI 2025: carga unica BigQuery")
    p.add_argument("--saida",required=True)
    p.add_argument("--live",action="store_true")
    p.add_argument("--confirmar-carga-unica",action="store_true")
    a=p.parse_args(argv)
    if not a.live or not a.confirmar_carga_unica:
        print(json.dumps({"estado":"BLOQUEADO_SEM_CONFIRMACAO"}))
        return 2
    try:
        resultado=carregar(baixar_pdf(),data_coleta=datetime.now(timezone.utc))
        out=Path(a.saida)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(resultado,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(resultado,ensure_ascii=False))
        return 0
    except Exception as exc:
        import sys
        print(json.dumps({"estado":"CARGA_RGI_FALHOU","tipo":type(exc).__name__,
                          "motivo":str(exc)[:220]},ensure_ascii=False),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
