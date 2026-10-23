"""NIVON: permissão observada por API IAM, sem qualquer operação de escrita.

O resultado de testIamPermissions é APENAS um indício, não prova a autorização
do workflow de escrita (WIF restringe também workflow_ref) e não prova que
uploads, jobs e MERGEs funcionarão. Recursos ausentes são tratados à parte.
"""
from __future__ import annotations

import argparse
import json
import re

PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
DATASET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
PERMISSOES_GCS = ("storage.objects.get", "storage.objects.create",
                  "storage.objects.list")
REGIAO = "southamerica-east1"


class ErroPreflight(ValueError):
    pass


def auditar(*, projeto, dataset, bucket, bq, storage, not_found, forbidden):
    if (not isinstance(projeto,str) or not PROJECT.fullmatch(projeto)
            or not isinstance(dataset,str) or not DATASET.fullmatch(dataset)
            or not isinstance(bucket,str) or not BUCKET.fullmatch(bucket)
            or ".." in bucket):
        raise ErroPreflight("identificadores GCP invalidos")
    resultado={"projeto":projeto,"dataset":dataset,"bucket":bucket,
               "status":"PRE_FLIGHT_READ_ONLY",
               "consulta_iam_informativa":True,"acesso_workflow_escrita_comprovado":False,
               "escritas":0,"jobs_bigquery":0,"upload_real_confirmado":False,
               "bigquery_write_confirmado":False}
    d=bq.get_dataset(f"{projeto}.{dataset}")
    g=storage.get_bucket(bucket)
    if (str(d.location).lower()!=REGIAO or str(g.location).lower()!=REGIAO
            or d.project!=projeto or d.dataset_id!=dataset
            or g.name!=bucket):
        raise ErroPreflight("regiao ou recursos divergentes")
    resultado["regiao"]=REGIAO

    try:
        obtidas=set(g.test_iam_permissions(PERMISSOES_GCS,client=storage,timeout=25))
    except forbidden:
        resultado["gcs_iam"]={"estado":"SEM_ACESSO_PARA_TESTE"}
    else:
        resultado["gcs_iam"]={
            "estado":"RESPOSTA_INFORMATIVA_NAO_E_PROVA_DE_UPLOAD",
            "objeto_leitura_indicado":"storage.objects.get" in obtidas,
            "objeto_criacao_indicado":"storage.objects.create" in obtidas,
            "objeto_listagem_indicado":"storage.objects.list" in obtidas}
    for nome in ("nivon_observacoes","agro_publicacoes_staging"):
        try:
            t=bq.get_table(f"{projeto}.{dataset}.{nome}")
        except not_found:
            resultado[nome]="AUSENTE"
        except forbidden:
            resultado[nome]="SEM_ACESSO"
        else:
            result=(str(getattr(getattr(t,"time_partitioning",None),"field",""))
                    == ("data_referencia" if nome=="nivon_observacoes"
                        else "data_coleta"))
            resultado[nome]="PARTICAO_VALIDADA" if result else "PARTICAO_DIVERGENTE"
    return resultado


def main(argv=None):
    p=argparse.ArgumentParser(description="Auditoria IAM consultiva sem escrita")
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--bucket",required=True)
    a=p.parse_args(argv)
    from google.cloud import bigquery,storage
    from google.api_core.exceptions import NotFound,Forbidden
    resultado=auditar(projeto=a.projeto,dataset=a.dataset,bucket=a.bucket,
        bq=bigquery.Client(project=a.projeto),
        storage=storage.Client(project=a.projeto),
        not_found=NotFound,forbidden=Forbidden)
    print(json.dumps(resultado,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
