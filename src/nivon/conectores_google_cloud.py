"""Executor real NIVON: captura pontual -> parser homologavel -> GCS RAW -> BQ MERGE.

Não provisiona cloud, não ativa fontes legado automaticamente e não publica
indicadores. Workload Identity/ADC externo, sem keys no repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .bcb_sgs_selic import URL_PONTUAL
from .conectores_fontes_prioritarias import (
    CONAB_URL, SGS_URL, MIME, normalizar,
)
from .ptax_plano import planejar_consultas_ptax
from .carga_bigquery_fontes import planejar_carga

PERMITIDAS = {
    "BCB_SGS_TAXA_SELIC_DIARIA": ("api.bcb.gov.br", 250_000),
    "BCB_PTAX": ("olinda.bcb.gov.br", 1_000_000),
    "CONAB_ARMAZENS_CAPACIDADE": ("portaldeinformacoes.conab.gov.br", 120_000_000),
}
DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{10,150}$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{2,61}[a-z0-9]$")
ID = re.compile(r"^[A-Z][A-Z0-9_]{2,90}$")
REPO = "brunocapellari-dotcom/NIVON"
MAX_OBS = 75000


class ErroConectorCloud(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def plano_url(dataset: str, *, inicio: str | None = None,
              fim: str | None = None) -> str:
    if dataset == "BCB_SGS_TAXA_SELIC_DIARIA":
        return SGS_URL
    if dataset == "CONAB_ARMAZENS_CAPACIDADE":
        return CONAB_URL
    if dataset == "BCB_PTAX":
        fim = fim or date.today().isoformat()
        inicio = inicio or (date.fromisoformat(fim) - timedelta(days=4)).isoformat()
        plans=planejar_consultas_ptax(moeda="USD",inicio=inicio,fim=fim)
        if len(plans) != 1:
            raise ErroConectorCloud("PTAX requer janela de ate 20 dias por chamada")
        return plans[0]["url"]
    raise ErroConectorCloud("dataset sem conexao HTTP pronta")


def obter_https(dataset: str, url: str, *, cliente=None) -> bytes:
    """Permite somente URL de fonte fixa e HTTPS sem redirects automáticos."""
    if dataset not in PERMITIDAS:
        raise ErroConectorCloud("fonte sem coletor publico homologavel")
    host, limite=PERMITIDAS[dataset]
    uri=urlsplit(url)
    if (uri.scheme!="https" or uri.hostname!=host or uri.username or uri.password
            or uri.fragment or uri.port not in (None,443) or len(url)>1500):
        raise ErroConectorCloud("destino HTTP externo rejeitado")
    if dataset != "BCB_PTAX" and url != plano_url(dataset):
        raise ErroConectorCloud("endpoint fora da rota canônica")
    if dataset == "BCB_PTAX" and (
            not uri.path.startswith("/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarPeriodo(")
            or "$format=json" not in uri.query):
        raise ErroConectorCloud("rota PTAX não corresponde ao planejador")
    abrir=cliente if cliente is not None else build_opener(_SemRedirect())
    req=Request(url,headers={"Accept":"application/json,text/plain,application/octet-stream",
                             "User-Agent":"NIVON/0.1 ColetorAutorizado"})
    with abrir.open(req,timeout=35) as resposta:
        status=int(resposta.status)
        if status!=200 or resposta.geturl()!=url:
            raise ErroConectorCloud("status ou redirect inesperado")
        mime=str(resposta.headers.get("Content-Type","")).lower().split(";",1)[0].strip()
        if dataset=="CONAB_ARMAZENS_CAPACIDADE":
            aceitos={"text/plain","application/octet-stream","text/csv"}
        else:
            aceitos={"application/json","text/json","text/plain"}
        if mime not in aceitos:
            raise ErroConectorCloud("MIME não esperado")
        raw=resposta.read(limite+1)
    if not isinstance(raw,bytes) or not 0<len(raw)<=limite:
        raise ErroConectorCloud("RAW vazio/grande")
    amostra=raw[:1024].lstrip().lower()
    if b"<html" in amostra or b"<!doctype html" in amostra or b"request rejected" in amostra:
        raise ErroConectorCloud("pagina HTML/WAF, não dataset")
    return raw


def obter_drive_imea(file_id: str, *, drive=None) -> tuple[bytes,str]:
    """Mirror autenticado IMEA em Drive; NÃO substitui feed da editora."""
    if not isinstance(file_id,str) or not DRIVE_ID.fullmatch(file_id):
        raise ErroConectorCloud("identificador Drive inválido")
    if drive is None:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("instalar extra google-api-python-client para Drive") from exc
        drive=build("drive","v3",cache_discovery=False)
    meta=drive.files().get(fileId=file_id,fields="id,name,mimeType,size,modifiedTime",
                           supportsAllDrives=True).execute()
    mime=meta.get("mimeType")
    if mime not in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.google-apps.spreadsheet",
    }:
        raise ErroConectorCloud("workbook IMEA não é XLSX ou Google Sheet")
    tamanho=int(meta.get("size") or 0)
    if tamanho>25_000_000:
        raise ErroConectorCloud("IMEA workbook grande demais")
    if mime=="application/vnd.google-apps.spreadsheet":
        req=drive.files().export_media(fileId=file_id,
                 mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        req=drive.files().get_media(fileId=file_id,supportsAllDrives=True)
    # Leitura em memoria limitada. Google Drive client de terceiros não é
    # considerado fonte original de publicação nem prova de direitos.
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise RuntimeError("biblioteca Drive necessária") from exc
    import io
    buf=io.BytesIO()
    download=MediaIoBaseDownload(buf,req,chunksize=1024*1024)
    concluido=False
    while not concluido:
        _,concluido=download.next_chunk()
        if buf.tell()>25_000_000:
            raise ErroConectorCloud("IMEA excedeu limite durante download")
    raw=buf.getvalue()
    if not raw.startswith(b"PK\x03\x04"):
        raise ErroConectorCloud("IMEA não retornou XLSX")
    return raw,f"https://drive.google.com/file/d/{file_id}/view"


def cloud_config(ambiente=None) -> dict:
    env=os.environ if ambiente is None else ambiente
    required={
        "projeto":env.get("NIVON_BQ_PROJECT", ""),
        "dataset":env.get("NIVON_BQ_DATASET", ""),
        "bucket":env.get("NIVON_GCS_BUCKET",""),
    }
    if (env.get("NIVON_GCP_COLLECT_ENABLED")!="true"
            or env.get("NIVON_ZERO_COST_BQ_APPROVED")!="true"):
        raise PermissionError("coleta cloud sem gate operacional e orçamento explicitamente aprovados")
    from .carga_bigquery_fontes import PROJECT,DATASET
    if (not PROJECT.fullmatch(required["projeto"]) or
            not DATASET.fullmatch(required["dataset"]) or
            not BUCKET.fullmatch(required["bucket"])):
        raise ErroConectorCloud("configuração GCP incompleta/inválida")
    return required


def construir_jsonl(lote: dict, *, gcs_uri: str, destino: str | Path) -> dict:
    """Usa o MESMO contrato do carregador existente, sem novo mart concorrente."""
    if not isinstance(lote,dict) or not ID.fullmatch(lote.get("dataset_id","")):
        raise ErroConectorCloud("lote sem identidade")
    if not re.fullmatch(r"gs://[a-z0-9._-]+/raw/[A-Z0-9_]+/[a-f0-9]{64}\.bin",gcs_uri):
        raise ErroConectorCloud("referência GCS insegura")
    if not gcs_uri.endswith(lote["sha256"]+".bin"):
        raise ErroConectorCloud("referência RAW/hash inconsistente")
    if not 1<=len(lote["registros"])<=MAX_OBS:
        raise ErroConectorCloud("lote vazio/grande")
    sid=hashlib.sha256((lote["dataset_id"]+"|"+lote["sha256"]).encode()).hexdigest()
    path=Path(destino)
    if path.is_symlink():
        raise ErroConectorCloud("destino não pode ser symlink")
    identidades=set()
    count=0
    with path.open("w",encoding="utf-8") as output:
        for row in lote["registros"]:
            identidade=row.get("identidade")
            if not isinstance(identidade,str) or not 1<=len(identidade)<=180:
                raise ErroConectorCloud("identidade de registro inválida")
            referencia=row.get("referencia")
            if not isinstance(referencia,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",referencia):
                raise ErroConectorCloud("data_referencia obrigatória")
            try:
                date.fromisoformat(referencia)
            except ValueError as exc:
                raise ErroConectorCloud("referência inválida") from exc
            natureza=row.get("natureza")
            if natureza not in {"OBSERVADO","INFORMADO","ESTIMADO","PROJETADO","INFERIDO"}:
                raise ErroConectorCloud("natureza não categorizada")
            fields=dict(row.get("campos") or {})
            fields.update({"raw_sha256":lote["sha256"],"raw_gcs_uri":gcs_uri,
                           "fonte_url":lote["origem"],
                           "qualidade_fonte":lote["qa"],
                           "data_coleta":lote["coletado_em"],
                           "data_publicacao":row.get("publicacao"),
                           "data_referencia":referencia,
                           "competencia":row.get("competencia") or referencia[:7],
                           "aprovado_para_publicacao":False})
            conteudo=json.dumps(fields,sort_keys=True,ensure_ascii=False,
                                 separators=(",",":"),allow_nan=False)
            chave=identidade+"|"+referencia+"|"+conteudo
            fingerprint=hashlib.sha256(chave.encode("utf-8")).hexdigest()
            if (identidade,fingerprint) in identidades:
                raise ErroConectorCloud("chave duplicada no lote")
            identidades.add((identidade,fingerprint))
            obj={"dataset_id":lote["dataset_id"],"identidade":identidade,
                 "fingerprint":fingerprint,"referencia":referencia,
                 "competencia":row.get("competencia") or referencia[:7],
                 "publicacao":row.get("publicacao"),
                 "coletado_em":lote["coletado_em"],"unidade":row.get("unidade"),
                 "valor":None if row.get("valor") is None else str(row["valor"]),
                 "campos":fields,"snapshot_id":sid,"natureza":natureza}
            output.write(json.dumps(obj,ensure_ascii=False,allow_nan=False)+"\n")
            count+=1
    if path.stat().st_size>65_000_000:
        raise ErroConectorCloud("JSONL extrapola o contrato existente BigQuery")
    return {"linhas":count,"arquivo":str(path),
            "snapshot_id":sid,"gcs_raw":gcs_uri}


def upload_raw_gcs(lote: dict, *, bucket: str, client=None) -> dict:
    """Escrita condicional imutável por hash no bucket privado já provisionado."""
    if not BUCKET.fullmatch(bucket):
        raise ErroConectorCloud("bucket inválido")
    if client is None:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("instalar google-cloud-storage para upload RAW") from exc
        client=storage.Client()
    key=f"raw/{lote['dataset_id']}/{lote['sha256']}.bin"
    blob=client.bucket(bucket).blob(key)
    uri=f"gs://{bucket}/{key}"
    if blob.exists():
        blob.reload()
        meta=blob.metadata or {}
        if meta.get("sha256")!=lote["sha256"] or blob.size!=len(lote["raw"]):
            raise ErroConectorCloud("objeto RAW existente com integridade divergente")
        return {"uri":uri,"novo":False}
    blob.metadata={"sha256":lote["sha256"],
                   "dataset_id":lote["dataset_id"],
                   "coletado_em":lote["coletado_em"]}
    blob.upload_from_string(lote["raw"],content_type=lote["tipo"],
                            if_generation_match=0)
    return {"uri":uri,"novo":True}


def enviar_lote_gcp(lote: dict, *, config: dict, storage_client=None,
                    load_callback=None) -> dict:
    """Orquestra GCS -> JSONL -> BigQuery; falha sem habilitar publicação."""
    gcs=upload_raw_gcs(lote,bucket=config["bucket"],client=storage_client)
    with tempfile.TemporaryDirectory(prefix="nivon-cloud-") as pasta:
        arquivo=Path(pasta)/"lote.jsonl"
        stage=construir_jsonl(lote,gcs_uri=gcs["uri"],destino=arquivo)
        plano=planejar_carga(arquivo=arquivo,project_id=config["projeto"],
                            dataset_id=config["dataset"])
        if load_callback is None:
            from .carga_bigquery_fontes import executar_carga
            bq=executar_carga(arquivo=arquivo,project_id=config["projeto"],
                              dataset_id=config["dataset"],executar=True)
        else:
            bq=load_callback(arquivo,config)
    return {
        "status":"CARGA_BIGQUERY_EXECUTADA" if bq.get("executado") else "CARGA_NAO_CONFIRMADA",
        "dataset_id":lote["dataset_id"],"observacoes":stage["linhas"],
        "sha256":lote["sha256"],"gcs":gcs,"bigquery":bq,
        "publicacao_editorial":False,
    }


def executar_fonte(dataset: str, *, inicio=None, fim=None,
                   drive_id=None, cliente_http=None, cliente_drive=None,
                   storage_client=None, load_callback=None,
                   ambiente=None, agora=None) -> dict:
    cfg=cloud_config(ambiente)
    env=os.environ if ambiente is None else ambiente
    if env.get(f"NIVON_FONTE_{dataset}_ATIVA")!="true":
        raise PermissionError("fonte sem gate individual autorizado")
    if dataset=="IMEA_WORKBOOK_LEGADO_STAGING":
        if env.get("NIVON_IMEA_DIREITOS_CONFIRMADOS")!="true":
            raise PermissionError("IMEA exige direitos de coleta e armazenamento autorizados")
        if len((env.get("NIVON_IMEA_EVIDENCIA_DIREITOS") or "").strip())<10:
            raise PermissionError("IMEA sem evidência de direitos")
        raw,url=obter_drive_imea(drive_id or env.get("NIVON_IMEA_DRIVE_FILE_ID",""),
                                  drive=cliente_drive)
    else:
        url=plano_url(dataset,inicio=inicio,fim=fim)
        raw=obter_https(dataset,url,cliente=cliente_http)
    now=agora or datetime.now(timezone.utc).isoformat()
    lote=normalizar(dataset,raw,origem=url,coletado_em=now)
    result=enviar_lote_gcp(lote,config=cfg,storage_client=storage_client,
                           load_callback=load_callback)
    result["modo"]="FONTE_ESPECIFICA_SEM_PROMOCAO"
    return result


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="NIVON: captura controlada e persistência GCS + BigQuery")
    p.add_argument("--fonte",required=True,choices=sorted(set(PERMITIDAS)|
                                                         {"IMEA_WORKBOOK_LEGADO_STAGING"}))
    p.add_argument("--inicio")
    p.add_argument("--fim")
    p.add_argument("--drive-id")
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    if not args.executar:
        result={"fonte":args.fonte,"status":"PLANO_SEM_REDE",
                "destino":"GCS_RAW_PRIVADO_E_BIGQUERY_JA_PROVISIONADOS",
                "gate":"--executar e variáveis GCP + fonte e direitos",
                "coleta":False}
    else:
        result=executar_fonte(args.fonte,inicio=args.inicio,fim=args.fim,drive_id=args.drive_id)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
