"""Carga BigQuery explícita e idempotente das observações NIVON em JSONL.

Usa ADC/Workload Identity externo; NUNCA lê chaves JSON do repositório.
Sem provisionar projeto/dataset, sem ações em cron; valida custo e schema.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from hashlib import sha256
from uuid import uuid4

PROJECT=re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
DATASET=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")
SHA=re.compile(r"^[a-f0-9]{64}$")
COLS=("dataset_id","identidade","fingerprint","referencia","competencia",
      "publicacao","coletado_em","unidade","valor","campos","snapshot_id","natureza")
MAX_BYTES=12_000_000
MAX_ROWS=50000

class ErroCargaBigQuery(ValueError):
    pass

def planejar_carga(*,arquivo,project_id,dataset_id,max_bytes_billed=10_000_000):
    if not isinstance(project_id,str) or not PROJECT.fullmatch(project_id):
        raise ErroCargaBigQuery("project_id fora do formato permitido")
    if not isinstance(dataset_id,str) or not DATASET.fullmatch(dataset_id):
        raise ErroCargaBigQuery("dataset_id fora do formato permitido")
    if type(max_bytes_billed) is not int or not 1_000_000<=max_bytes_billed<=100_000_000:
        raise ErroCargaBigQuery("limite de bytes faturaveis invalido")
    path=Path(arquivo)
    if path.is_symlink() or not path.is_file() or path.suffix!=".jsonl" or not 1<=path.stat().st_size<=MAX_BYTES:
        raise ErroCargaBigQuery("arquivo ausente, symlink ou acima do limite")
    n=0
    seen=set()
    with path.open(encoding="utf-8") as f:
        for row in f:
            n+=1
            if n>MAX_ROWS:
                raise ErroCargaBigQuery("muitas linhas")
            try:
                obj=json.loads(row)
            except (ValueError,UnicodeError) as exc:
                raise ErroCargaBigQuery("JSONL invalido") from exc
            if not isinstance(obj,dict) or not set(COLS)<=set(obj):
                raise ErroCargaBigQuery("contrato de colunas incompleto")
            if not all(isinstance(obj[k],str) and SHA.fullmatch(obj[k]) for k in ("fingerprint","snapshot_id")):
                raise ErroCargaBigQuery("fingerprint/snapshot invalido")
            key=(obj["dataset_id"],obj["identidade"],obj["fingerprint"])
            if key in seen:
                raise ErroCargaBigQuery("duplicacao em lote")
            seen.add(key)
            if obj["natureza"] not in ("OBSERVADO","INFORMADO","ESTIMADO","PROJETADO","INFERIDO"):
                raise ErroCargaBigQuery("natureza invalida")
    return {"tabela":f"{project_id}.{dataset_id}.nivon_observacoes",
         "projeto":project_id,"dataset":dataset_id,"linhas":n,
         "arquivo":str(path),"sha256":sha256(path.read_bytes()).hexdigest(),
         "max_bytes_billed":max_bytes_billed,
         "executado":False,"credencial_requerida":"GOOGLE_APPLICATION_CREDENTIALS ou Workload Identity"}

def executar_carga(*,arquivo,project_id,dataset_id,executar=False,
                   max_bytes_billed=10_000_000,client=None):
    p=planejar_carga(arquivo=arquivo,project_id=project_id,dataset_id=dataset_id,
                    max_bytes_billed=max_bytes_billed)
    if executar is not True:
        raise PermissionError("BIGQUERY_UPLOAD_OFF")
    # Import tardio evita dependencia GCP em coletores/testes offline.
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError("instale extra opcional google-cloud-bigquery; usar ADC") from exc
    cli=client if client is not None else bigquery.Client(project=project_id)
    target=p["tabela"]
    # Validar tabela e dataset existentes. Sem provisionar nuvem automaticamente.
    cli.get_dataset(f"{project_id}.{dataset_id}")
    cli.get_table(target)
    staging=f"{project_id}.{dataset_id}._nivon_stage_{uuid4().hex[:24]}"
    campos=[("dataset_id","STRING"),("identidade","STRING"),("fingerprint","STRING"),
            ("referencia","STRING"),("competencia","STRING"),("publicacao","STRING"),
            ("coletado_em","STRING"),("unidade","STRING"),("valor","STRING"),
            ("campos","JSON"),("snapshot_id","STRING"),("natureza","STRING")]
    job_config=bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=[bigquery.SchemaField(k,t) for k,t in campos],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
    )
    try:
        with open(arquivo,"rb") as fp:
            cli.load_table_from_file(fp,staging,job_config=job_config).result(timeout=150)
        coluna=", ".join(COLS)
        # Deduplicar na staging por chave já validada antes de enviar.
        on=" AND ".join(f"T.{k}=S.{k}" for k in ("dataset_id","identidade","fingerprint"))
        sql=(f"MERGE \`{target}\` T USING \`{staging}\` S ON {on} "
             f"WHEN NOT MATCHED THEN INSERT ({coluna}) VALUES ("+
             ", ".join("S."+k for k in COLS)+")")
        cfg=bigquery.QueryJobConfig(maximum_bytes_billed=p["max_bytes_billed"])
        done=cli.query(sql,job_config=cfg).result(timeout=150)
        p.update({"executado":True,"projeto":project_id,"linhas_enviadas":p["linhas"],
                  "nuvem":"BIGQUERY","dados_publicados":False})
    finally:
        cli.delete_table(staging,not_found_ok=True)
    return p

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description="NIVON: stage JSONL -> BigQuery")
    parser.add_argument("--arquivo",required=True)
    parser.add_argument("--projeto",required=True)
    parser.add_argument("--dataset",required=True)
    parser.add_argument("--executar",action="store_true")
    args=parser.parse_args(argv)
    kwargs={"arquivo":args.arquivo,"project_id":args.projeto,"dataset_id":args.dataset}
    out=(executar_carga(**kwargs,executar=True) if args.executar else planejar_carga(**kwargs))
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
