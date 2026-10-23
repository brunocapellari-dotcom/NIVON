"""Persistência idempotente de sinais CKAN ZARC no Neon AGRO (não em PTAX).

Contrato: exclusivamente metadados do CKAN, não dados de produção. Requer
psycopg connection fornecida pelo executor (segredo fica fora do código).
Nunca modifica flags de coleta/publicação ou escreve nas tabelas de ZARC.
"""
from __future__ import annotations

import re
from datetime import datetime,timezone

from .zarc_sinais_ckan import RESOURCE_ID,DATASET_ID,FONTE_ID

ALLOWED_HOST="ep-fancy-lake-b6xqxo0u.c-2.sa-east-1.aws.neon.tech"
DATABASE="nivon_agro"
_SHA=re.compile(r"[a-f0-9]{64}\Z")

class ErroSinalNeon(ValueError):
    pass

def _utc(dt):
    if not isinstance(dt,str):
        raise ErroSinalNeon("COLETA_INVALIDA")
    try:
        stamp=datetime.fromisoformat(dt.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroSinalNeon("COLETA_INVALIDA") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ErroSinalNeon("COLETA_SEM_FUSO")
    return stamp.astimezone(timezone.utc)

def _validar_conexao(conn):
    info=getattr(conn,"info",None)
    if (info is None or getattr(info,"host",None)!=ALLOWED_HOST
            or getattr(info,"dbname",None)!=DATABASE):
        raise PermissionError("CONEXAO_NAO_E_NIVON_AGRO_DADOS")
    if getattr(conn,"closed",True):
        raise ErroSinalNeon("CONEXAO_FECHADA")

def gravar_sinal_ckan(*,conn,sinal,executar=False):
    """Uma linha por horário observado; nunca guarda URL assinada."""
    if executar is not True:
        raise PermissionError("GRAVACAO_NEON_OFF_POR_PADRAO")
    _validar_conexao(conn)
    if (not isinstance(sinal,dict) or sinal.get("dataset_id")!=DATASET_ID
            or sinal.get("source_id")!="ZARC"
            or sinal.get("resource_id")!=RESOURCE_ID
            or sinal.get("versao_csv_sha256") is not None
            or sinal.get("consegue_provar_arquivo_alterado") is not False):
        raise ErroSinalNeon("SINAL_NAO_E_METADATA_CKAN")
    sha=sinal.get("metadata_fingerprint")
    license_id=sinal.get("licenca_declarada")
    if (not isinstance(sha,str) or not _SHA.fullmatch(sha)
            or license_id not in ("cc-by","cc-by-3.0","cc-by-4.0")):
        raise ErroSinalNeon("SHA_OU_LICENCA_NAO_HOMOLOGADOS")
    coleta=_utc(sinal.get("coleta_utc"))
    def val(k):
        v=sinal.get(k)
        if v is None: return None
        if not isinstance(v,str) or len(v)>150:
            raise ErroSinalNeon("VALOR_CKAN_INVALIDO")
        return v
    params=(RESOURCE_ID,coleta,sha,license_id,val("pacote_revision_id"),
            val("recurso_revision_id"),val("pacote_modified"),
            val("recurso_modified"),"MAPA_CKAN_ZARC",
            "https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO nivon_agro_staging.zarc_ckan_sinais(
              resource_id,coletado_em,metadata_fingerprint,licenca_declarada,
              pacote_revision_id,recurso_revision_id,pacote_modified_text,
              recurso_modified_text,fonte_registro,prova_url)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT(resource_id,coletado_em) DO NOTHING""",params)
            inseriu=cur.rowcount==1
            cur.execute("""SELECT metadata_fingerprint FROM
                 nivon_agro_staging.zarc_ckan_sinais
                 WHERE resource_id=%s AND coletado_em=%s""",(RESOURCE_ID,coleta))
            row=cur.fetchone()
            if row is None or row[0]!=sha:
                raise ErroSinalNeon("MESMA_COLETA_COM_METADATA_DIVERGENTE")
            cur.execute("""SELECT metadata_fingerprint FROM
                 nivon_agro_staging.zarc_ckan_sinais
                 WHERE resource_id=%s AND coletado_em<%s
                 ORDER BY coletado_em DESC LIMIT 1""",(RESOURCE_ID,coleta))
            prev=cur.fetchone()
    return {
        "dataset_id":DATASET_ID,
        "coleta_utc":coleta.isoformat(),
        "nova_coleta":inseriu,
        "mudanca_metadados_frente_coleta_anterior":(
            prev is not None and prev[0]!=sha),
        "conteudo_csv_alterado_comprovado":False,
        "observacao_ckan_persistida":True,
        "dados_agricolas_inseridos":False,
        "publicavel":False,
    }
