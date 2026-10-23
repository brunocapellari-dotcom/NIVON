"""Migração inicial do módulo marítimo NIVON no BigQuery existente.

Sem mutações por padrão. A aplicação exige --aplicar, autorização do
projeto real e usa ADC/WIF; nunca gera senhas nem cria novos projetos,
buckets ou datasets. CREATE TABLE IF NOT EXISTS é idempotente.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

PADRAO = Path(__file__).with_name("maritimo_bigquery.sql")
EXPECTED = ("capturas","escalas_revisoes","fluxos_passagens","coleta_execucoes")
PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
DATASET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")


def gerar_sql(*, projeto, dataset, fonte=PADRAO):
    if not isinstance(projeto,str) or not PROJECT.fullmatch(projeto):
        raise ValueError("project id GCP invalido")
    if not isinstance(dataset,str) or not DATASET.fullmatch(dataset):
        raise ValueError("dataset BigQuery invalido")
    texto=Path(fonte).read_text(encoding="utf-8")
    if texto.count("NIVON_PROJECT_ID")!=6 or texto.count("NIVON_DATASET_ID")!=6:
        raise ValueError("template SQL esperado mudou; revisar migracao")
    conteudo=texto.replace("NIVON_PROJECT_ID",projeto).replace("NIVON_DATASET_ID",dataset)
    expected=[f"{projeto}.{dataset}.{n}" for n in EXPECTED]
    if any(n not in conteudo for n in expected):
        raise ValueError("faltam tabelas esperadas no schema")
    if f"{projeto}.{dataset}.estado_fontes_v" not in conteudo:
        raise ValueError("view de monitoramento ausente")
    if "data_referencia DATE" not in conteudo or "data_coleta TIMESTAMP" not in conteudo:
        raise ValueError("campos temporais canônicos ausentes")
    return conteudo


def aplicar_sql(sql, *, projeto, dataset, autorizado=False, client=None):
    if not autorizado:
        raise PermissionError("migração bloqueada: execução requer --aplicar")
    # Confirmar primeiro que dataset preexistente é consultável.
    if client is None:
        from google.cloud import bigquery
        client=bigquery.Client(project=projeto,location="southamerica-east1")
    ref=f"{projeto}.{dataset}"
    client.get_dataset(ref)
    # DDL BigQuery multi-statement. Tabelas são criadas somente no dataset validado.
    client.query(sql).result(timeout=180)
    for name in EXPECTED:
        client.get_table(ref+"."+name)
    return {"projeto":projeto,"dataset":dataset,
            "tabelas_verificadas":list(EXPECTED),"executado":True}


def main(argv=None):
    p=argparse.ArgumentParser(description="Preparação/aplicação DDL marítimo no BigQuery")
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",default="nivon_raw")
    p.add_argument("--saida",type=Path)
    p.add_argument("--aplicar",action="store_true")
    args=p.parse_args(argv)
    ddl=gerar_sql(projeto=args.projeto,dataset=args.dataset)
    if args.aplicar:
        resultado=aplicar_sql(ddl,projeto=args.projeto,dataset=args.dataset,autorizado=True)
        print("CRIADAS_OU_VERIFICADAS: "+",".join(resultado["tabelas_verificadas"]))
    elif args.saida:
        # exclusive: não sobrescrever SQL previamente auditado
        with args.saida.open("x",encoding="utf-8") as f:
            f.write(ddl)
        print("DDL_PREPARADO_SEM_EXECUCAO")
    else:
        print(ddl)


if __name__=="__main__":
    main()
