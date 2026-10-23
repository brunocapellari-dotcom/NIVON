"""BigQuery: persistencia historica canonica, sem senha/DSN (ADC no Cloud Run).

SQLite e buffer efemero. MERGE por chaves naturais para replay idempotente.
Nenhuma operacao programada/AIS vira carga realizada por efeito da escrita.
"""
from __future__ import annotations
import argparse
import json
import re
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone

CAMPOS = {
 "capturas":[("fonte","STRING"),("hash_conteudo","STRING"),
    ("primeiro_visto","TIMESTAMP"),("ultimo_visto","TIMESTAMP"),
    ("quantidade","INTEGER"),("qualidade_json","STRING")],
 "escalas_revisoes":[("fonte","STRING"),("escala_id","STRING"),
    ("revisao_sha256","STRING"),("data_referencia","DATE"),
    ("competencia","STRING"),("data_publicacao","TIMESTAMP"),
    ("data_coleta","TIMESTAMP"),("natureza","STRING"),("situacao","STRING"),
    ("publicavel","BOOLEAN"),("payload_json","STRING")],
 "fluxos_passagens":[("fonte","STRING"),("passagem","STRING"),
    ("data_referencia","DATE"),("revisao_sha256","STRING"),
    ("data_coleta","TIMESTAMP"),("transitos_ais","INTEGER"),
    ("volume_transito_estimado_t","FLOAT"),("payload_json","STRING")],
 "coleta_execucoes":[("run_id","STRING"),("fonte","STRING"),
    ("data_coleta","TIMESTAMP"),("estado","STRING"),
    ("quantidade","INTEGER"),("revisoes","INTEGER"),
    ("captura_sha256","STRING"),("motivo","STRING"),("duracao_ms","INTEGER")],
}
CHAVES = {
 "capturas":["fonte","hash_conteudo"],
 "escalas_revisoes":["fonte","escala_id","revisao_sha256"],
 "fluxos_passagens":["fonte","passagem","data_referencia","revisao_sha256"],
 "coleta_execucoes":["run_id","fonte"],
}
MAX_LINHAS = 4000

def validar_destino(projeto, dataset):
    if not isinstance(projeto,str) or not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]",projeto):
        raise ValueError("projeto GCP invalido")
    if not isinstance(dataset,str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,255}",dataset):
        raise ValueError("dataset BigQuery invalido")
    return f"{projeto}.{dataset}"

def data_utc(value):
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp sem timezone")
    return dt.astimezone(timezone.utc).isoformat()

def referencia(value):
    raw=str(value or "").strip().split(" ")[0]
    for fmt in ("%Y-%m-%d","%d/%m/%Y"):
        try: return datetime.strptime(raw[:10],fmt).date().isoformat()
        except ValueError: pass
    return None

def ler_sqlite(path, table, optional=False):
    if path is None: return []
    if table not in ("capturas","revisoes","lote_execucoes","portwatch_diario"):
        raise ValueError("tabela SQLite fora da allowlist")
    path=Path(path)
    if not path.is_file():
        raise FileNotFoundError("arquivo de coleta ausente")
    with sqlite3.connect(str(path)) as con:
        con.row_factory=sqlite3.Row
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
        if not exists:
            if optional: return []
            raise ValueError("tabela historica ausente")
        count=con.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
        if count>MAX_LINHAS:
            raise ValueError("lote excede limite; dividir antes de persistir")
        return [dict(r) for r in con.execute("SELECT * FROM "+table)]

def preparar_linhas(banco, portwatch_banco=None):
    snaps=[]
    for r in ler_sqlite(banco,"capturas"):
        snaps.append(dict(fonte=r["fonte"],hash_conteudo=r["hash_conteudo"],
            primeiro_visto=data_utc(r["primeiro_visto"]),ultimo_visto=data_utc(r["ultimo_visto"]),
            quantidade=int(r["quantidade"]),qualidade_json=r["qualidade"]))
    revisions=[]
    for r in ler_sqlite(banco,"revisoes"):
        data=json.loads(r["conteudo_json"])
        flags=data.get("flags_qualidade") or []
        ref=referencia(data.get("data_referencia"))
        public=bool(r["publicavel"]) and data.get("natureza")=="INFORMADO_PELA_FONTE"
        public=public and "QUARENTENA_NAO_PUBLICAR" not in flags and r["fonte"] not in (
            "santarem_cdp","vila_conde_cdp","itacoatiara_amaggi")
        revisions.append(dict(fonte=r["fonte"],escala_id=r["escala"],
           revisao_sha256=r["revisao"],data_referencia=ref,
           competencia=ref[:7] if ref else None,
           data_publicacao=data_utc(data["data_publicacao"]) if data.get("data_publicacao") else None,
           data_coleta=data_utc(r["primeiro_visto"]),natureza=data.get("natureza") or "DESCONHECIDA",
           situacao=data.get("status"),publicavel=public,payload_json=r["conteudo_json"]))
    flows=[]
    for r in ler_sqlite(portwatch_banco,"portwatch_diario"):
        data=json.loads(r["dados_json"])
        if data.get("volume_realizado_t") is not None or data.get("natureza_volume_estimado")!="ESTIMADO_MODELO_FMI":
            raise ValueError("PortWatch nunca certifica carga realizada")
        flows.append(dict(fonte="FMI_PORTWATCH",passagem=r["passagem"],
           data_referencia=r["data_referencia"],revisao_sha256=r["revisao_sha256"],
           data_coleta=data_utc(r["coletado_em"]),transitos_ais=int(data["transitos_ais"]),
           volume_transito_estimado_t=data.get("volume_transito_estimado_t"),
           payload_json=r["dados_json"]))
    runs=[]
    for r in ler_sqlite(banco,"lote_execucoes",optional=True):
        if r["estado"] not in ("OK","QUARENTENA","FALHA"):
            raise ValueError("estado inesperado")
        runs.append(dict(run_id=r["run_id"],fonte=r["fonte"],data_coleta=data_utc(r["coletado_em"]),
           estado=r["estado"],quantidade=int(r["quantidade"]),revisoes=int(r["revisoes"]),
           captura_sha256=r["captura_sha256"],motivo=r["motivo"],duracao_ms=int(r["duracao_ms"])))
    return dict(capturas=snaps,escalas_revisoes=revisions,
                fluxos_passagens=flows,coleta_execucoes=runs)

def sql_merge(projeto,dataset,table,staging):
    base=validar_destino(projeto,dataset)
    if table not in CHAVES or not re.fullmatch(r"_staging_[a-z_]+_[0-9a-f]{16}",staging):
        raise ValueError("tabela de merge invalida")
    mark=chr(96)
    match=" AND ".join("T."+k+"=S."+k for k in CHAVES[table])
    update=("WHEN MATCHED AND S.ultimo_visto>T.ultimo_visto THEN "
            "UPDATE SET ultimo_visto=S.ultimo_visto ") if table=="capturas" else ""
    return (f"MERGE {mark}{base}.{table}{mark} T USING {mark}{base}.{staging}{mark} S "
            f"ON {match} {update}WHEN NOT MATCHED THEN INSERT ROW")

def sincronizar_bigquery(banco, *, portwatch_banco=None, projeto, dataset="nivon_raw",
                        client=None, bigquery_module=None, dry_run=False,
                        max_bytes_cobraveis=100_000_000):
    """Carga de staging + MERGE, fail-safe e recuperavel por replay.

    O dataset e tabelas devem existir (migracao SQL). Sem provisionamento
    implicito nem tabelas sinteticas no banco de producao.
    """
    base=validar_destino(projeto,dataset)
    if (type(max_bytes_cobraveis) is not int or
        not 10_000_000 <= max_bytes_cobraveis <= 1_000_000_000):
        raise ValueError("teto de bytes faturaveis BigQuery invalido")
    rows=preparar_linhas(banco,portwatch_banco)
    amounts={k:len(v) for k,v in rows.items()}
    if dry_run: return {"destino":base,"contagens":amounts,"gravado":False}
    if bigquery_module is None:
        from google.cloud import bigquery as bigquery_module
    if client is None:
        client=bigquery_module.Client(project=projeto)
    done=[]
    for table,payload in rows.items():
        if not payload: continue
        staging=f"_staging_{table}_{uuid.uuid4().hex[:16]}"
        target=base+"."+staging
        schema=[bigquery_module.SchemaField(field,typ) for field,typ in CAMPOS[table]]
        config=bigquery_module.LoadJobConfig(schema=schema,
                source_format=bigquery_module.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery_module.WriteDisposition.WRITE_EMPTY)
        try:
            client.load_table_from_json(payload,target,job_config=config).result()
            limit=bigquery_module.QueryJobConfig(maximum_bytes_billed=max_bytes_cobraveis)
            client.query(sql_merge(projeto,dataset,table,staging),job_config=limit).result()
            done.append(table)
        finally:
            client.delete_table(target,not_found_ok=True)
    return {"destino":base,"contagens":amounts,"aplicadas":done,"gravado":True}

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--banco",type=Path,required=True)
    p.add_argument("--portwatch-banco",type=Path)
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",default="nivon_raw")
    p.add_argument("--max-bytes-cobraveis",type=int,default=100_000_000)
    p.add_argument("--dry-run",action="store_true")
    args=p.parse_args(argv)
    out=sincronizar_bigquery(args.banco,portwatch_banco=args.portwatch_banco,
           projeto=args.projeto,dataset=args.dataset,dry_run=args.dry_run,
           max_bytes_cobraveis=args.max_bytes_cobraveis)
    print(json.dumps(out,ensure_ascii=False))

if __name__=="__main__":
    main()
