"""Inventário GCP do piloto ferroviário NIVON, SEM consultas SQL nem mutação.

Stage agro e terminal web hospedado são fases distintas. Nunca declarar
serviço Cloud Run implantado a partir de uma leitura da view ANTT.
"""
from __future__ import annotations

PROJETO="nivon-data"
DATASET="nivon_raw"
BUCKET="nivon-data-raw-2026"
REGIAO="southamerica-east1"
VIEW="vw_antt_ferrovia_od_atual"
STAGE="agro_fonte_stage"


def consolidar(*, regiao_dataset, regiao_bucket, acesso_publico,
               tipo_view, stage) -> dict:
    if stage not in ("AUSENTE","SCHEMA_OK","SCHEMA_DIVERGENTE"):
        raise ValueError("estado stage nao reconhecido")
    bloqueios=[]
    if str(regiao_dataset).lower()!=REGIAO:
        bloqueios.append("REGIAO_DATASET")
    if str(regiao_bucket).lower()!=REGIAO:
        bloqueios.append("REGIAO_BUCKET")
    if acesso_publico!="enforced":
        bloqueios.append("BUCKET_SEM_PUBLIC_ACCESS_PREVENTION")
    if tipo_view!="VIEW":
        bloqueios.append("VIEW_FERROVIARIA_AUSENTE")
    return {"estado":"PILOTO_DADOS_READONLY_PRONTO" if not bloqueios
            else "PILOTO_DADOS_READONLY_BLOQUEADO",
            "bloqueios":bloqueios,"projeto":PROJETO,
            "dataset":DATASET,"bucket":BUCKET,
            "view_antt":tipo_view if tipo_view=="VIEW" else "NAO_COMPROVADA",
            "stage_agro":stage,
            "stage_agro_bloqueia_piloto_ferrovia":False,
            "consultas_sql_executadas":0,
            "terminal_cloud_run_implantado":"NAO_VERIFICADO",
            "libera_deploy":False,"libera_whatsapp":False}


def consultar_metadados(*, bq, storage, erro_nao_encontrado, tipos_stage):
    """Somente get_dataset/get_bucket/get_table; demais erros propagam."""
    ds=bq.get_dataset(f"{PROJETO}.{DATASET}")
    bucket=storage.get_bucket(BUCKET)
    pap=getattr(getattr(bucket,"iam_configuration",None),
                "public_access_prevention",None)
    try:
        view=bq.get_table(f"{PROJETO}.{DATASET}.{VIEW}")
        tipo=getattr(view,"table_type",None)
    except erro_nao_encontrado:
        tipo=None
    try:
        stage=bq.get_table(f"{PROJETO}.{DATASET}.{STAGE}")
        schema={f.name:str(f.field_type).upper() for f in stage.schema}
        partition=getattr(stage,"time_partitioning",None)
        stage_status=("SCHEMA_OK" if schema==tipos_stage and
                      partition is not None and
                      partition.field=="coletado_utc" else "SCHEMA_DIVERGENTE")
    except erro_nao_encontrado:
        stage_status="AUSENTE"
    return consolidar(
        regiao_dataset=ds.location,regiao_bucket=bucket.location,
        acesso_publico=pap,tipo_view=tipo,stage=stage_status)
