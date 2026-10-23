"""CONAB SICARM: TXT oficial grande -> GCS RAW privado -> agregado -> BigQuery.

Usa parser e Quality Gate existentes. O RAW pode conter dados de cadastro:
GCS recebe o original de forma privada, e o BigQuery somente agregados.
O formato não demonstra estoque/ocupação. Não efetua coleta sem autorização.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .conab_armazens import LAYOUT_CONAB_SICARM_HEADER_V1, agregar_capacidade_local, ErroArmazens
from .qualidade_conab_armazens import verificar_consistencia_armazens
from .ingestao_fontes_reais import gravar_lote
from .persistencia_google_cloud import _enviar_unico, executar_envio

CONAB_SICARM = "https://portaldeinformacoes.conab.gov.br/downloads/arquivos/ArmazensCadastrados.txt"
OPERACOES = frozenset({"COLETA","ARMAZENAMENTO","PROCESSAMENTO"})
MAX_RAW = 120_000_000


class ErroConabCloud(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


def baixar_txt_conab(*,abridor=None):
    """Requisição com endpoint fixo, sem redirect e com tamanho/MIME limitado."""
    opener=abridor if abridor is not None else build_opener(_SemRedirect())
    req=Request(CONAB_SICARM,headers={
        "Accept":"text/plain,text/csv,application/octet-stream",
        "User-Agent":"NIVON/0.1 coleta-fonte-oficial",
    })
    with opener.open(req,timeout=60) as resp:
        if int(resp.status)!=200 or resp.geturl()!=CONAB_SICARM:
            raise ErroConabCloud("CONAB: HTTP/WAF/redirect inesperado")
        mime=str(resp.headers.get("Content-Type","")).split(";",1)[0].strip().lower()
        if mime not in {"text/plain","text/csv","application/octet-stream"}:
            raise ErroConabCloud("CONAB: tipo de arquivo divergente")
        raw=resp.read(MAX_RAW+1)
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_RAW:
        raise ErroConabCloud("CONAB: RAW fora do limite")
    amostra=raw[:2048].lower().lstrip()
    if b"<html" in amostra or b"<!doctype html" in amostra or b"request rejected" in amostra:
        raise ErroConabCloud("CONAB: resposta HTML/WAF, nao cadastro")
    return raw,mime


def preparar_agregado(raw: bytes, *, coletado_em: str) -> dict:
    """Normaliza sem PII e marca referência como snapshot, não boletim oficial."""
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_RAW:
        raise ErroConabCloud("RAW ausente/grande")
    try:
        instante=datetime.fromisoformat(coletado_em.replace("Z","+00:00"))
    except (ValueError,AttributeError) as exc:
        raise ErroConabCloud("data_coleta inválida") from exc
    if instante.utcoffset() is None:
        raise ErroConabCloud("data_coleta sem timezone")
    utc=instante.astimezone(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="nivon-conab-") as pasta:
        file=Path(pasta)/"sicarm.txt"
        file.write_bytes(raw)
        try:
            a=agregar_capacidade_local(file,LAYOUT_CONAB_SICARM_HEADER_V1,
                                       coletado_em=utc)
        except ErroArmazens as exc:
            raise ErroConabCloud("CONAB layout oficial divergente") from exc
    q=verificar_consistencia_armazens(a)
    if q["estado"]!="CONSISTENCIA_INTERNA_OK_SEM_HOMOLOGACAO" or q["liberado_para_publicacao"]:
        raise ErroConabCloud("CONAB sem validação interna conservadora")
    return {"agregados":a["agregados"],"sha_original":a["sha256_original"],
            "coleta":utc,"referencia_snapshot":utc[:10],
            "qa":{"municipios":q["municipios"],"armazens":q["armazens"],
                  "total_t":q["total_t"],
                  "codigos_ibge_nao_conciliados":q["codigo_ibge_sem_resolucao"],
                  "homologado":False,"publicavel":False}}


def _snapshot_derivado(preparado: dict, *, original_uri: str) -> tuple[bytes,list[dict]]:
    """Separar original confidencial dos agregados a transmitir ao BigQuery."""
    ag=preparado["agregados"]
    ref=preparado["referencia_snapshot"]
    sha=preparado["sha_original"]
    if not original_uri.endswith(f"/{sha}.raw"):
        raise ErroConabCloud("GCS original nao corresponde ao hash")
    raw=json.dumps({"status":"AGREGADO_DERIVADO_NIVON_NAO_PUBLICAVEL",
                    "source_sha256":sha,"original_gcs":original_uri,
                    "qa":preparado["qa"],"agregados":ag},
                   ensure_ascii=False,sort_keys=True,separators=(",",":"),
                   allow_nan=False).encode("utf-8")
    regs=[]
    for x in ag:
        valor=x["capacidade_estatica_t"]
        regs.append({"identidade":f"CONAB_SICARM|{x['uf']}|{x['municipio_normalizado']}",
                     "referencia":ref,"competencia":ref[:7],
                     "publicacao":None,"natureza":"INFORMADO",
                     "unidade":"t","valor":valor,
                     "campos":{"uf":x["uf"],"municipio":x["municipio_normalizado"],
                               "codigo_ibge":x["codigo_ibge"],
                               "armazens_distintos":x["armazens_distintos"],
                               "capacidade_estatica_t":valor,
                               "raw_original_gcs":original_uri,
                               "raw_original_sha256":sha,
                               "derivado_nivon":True,
                               "data_referencia_tipo":"SNAPSHOT_COLETA_NAO_DATA_OFICIAL",
                               "capacidade_cadastrada_nao_estoque":True,
                               "publicacao_verificada":False,
                               "liberado_para_publicacao":False}})
    return raw,regs


def executar_conab_cloud(*,base,project_id,dataset_id,bucket,autorizacoes=frozenset(),
                        evidencia="",privacidade_verificada=False,
                        executar=False,abridor=None,storage_client=None,bq_loader=None,
                        instante=None) -> dict:
    if executar is not True or not OPERACOES <= set(autorizacoes):
        raise PermissionError("CONAB GCP requer aprovação por operação")
    if not isinstance(evidencia,str) or len(evidencia.strip())<10:
        raise PermissionError("evidência de direitos ausente")
    if privacidade_verificada is not True:
        raise PermissionError("bucket RAW de cadastro requer privacidade previamente verificada")
    raw,mime=baixar_txt_conab(abridor=abridor)
    dt=instante or datetime.now(timezone.utc)
    if not isinstance(dt,datetime) or dt.utcoffset() is None:
        raise ErroConabCloud("data da coleta inválida")
    preparado=preparar_agregado(raw,coletado_em=dt.isoformat())
    sha=preparado["sha_original"]
    if storage_client is None:
        from google.cloud import storage
        storage_client=storage.Client(project=project_id)
    remote=storage_client.bucket(bucket)
    if not remote.exists():
        raise ErroConabCloud("bucket de destino inexistente")
    with tempfile.TemporaryDirectory(prefix="nivon-sicarm-") as scratch:
        original=Path(scratch)/"sicarm.txt"
        original.write_bytes(raw)
        key=f"nivon/raw/original/CONAB_ARMAZENS_CAPACIDADE/{sha}.raw"
        estado=_enviar_unico(remote,arquivo=original,objeto=key,sha=sha,content_type=mime)
    uri=f"gs://{bucket}/{key}"
    agregado,registros=_snapshot_derivado(preparado,original_uri=uri)
    caminho=Path(base)
    dados=gravar_lote(banco=caminho/"fontes_reais.sqlite",
                      diretorio_bruto=caminho/"raw",
                      dataset_id="CONAB_ARMAZENS_CAPACIDADE",
                      origem=CONAB_SICARM,raw=agregado,
                      tipo="application/json",coletado_em=preparado["coleta"],
                      registros=registros,estado="NORMALIZED")
    enviado=executar_envio(base=caminho,bucket=bucket,project_id=project_id,
                           dataset_id=dataset_id,bigquery=True,executar=True,
                           autorizacoes=autorizacoes,evidencia=evidencia,
                           storage_client=storage_client,bq_loader=bq_loader)
    return {"estado":"GCS_BIGQUERY_AGREGADO_NAO_PUBLICAVEL",
            "fonte":"CONAB","dataset_id":"CONAB_ARMAZENS_CAPACIDADE",
            "original":{"gcs":uri,"estado":estado,"sha256":sha},
            "municipios":len(registros),
            "qa":preparado["qa"],
            "stage":dados["snapshot_id"],"gcp":enviado,
            "publicacao_automatica":False}


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: CONAB SICARM oficial -> GCS privado -> BigQuery agregado")
    p.add_argument("--base",default="data/nivon/cloud_conab")
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    if not args.executar:
        result={"modo":"PLANO","fonte":"CONAB_ARMAZENS_CAPACIDADE",
                "coleta":False,"pipeline":"HTTPS->QC->GCS RAW privado->SQLite agregado->GCS->BQ"}
    else:
        approved=(os.getenv("NIVON_GCP_OPERACIONAL_APROVADO")=="true" and
                  os.getenv("NIVON_ZERO_COST_BQ_APPROVED")=="true" and
                  os.getenv("NIVON_FONTE_CONAB_ARMAZENS_CAPACIDADE_ATIVA")=="true")
        if not approved:
            raise PermissionError("GCP CONAB não aprovado")
        result=executar_conab_cloud(
            base=args.base,project_id=os.environ["NIVON_BQ_PROJECT"],
            dataset_id=os.environ["NIVON_BQ_DATASET"],
            bucket=os.environ["NIVON_GCS_BUCKET"],
            autorizacoes=OPERACOES,evidencia=os.getenv("NIVON_GCP_RIGHTS_EVIDENCE",""),
            privacidade_verificada=(os.getenv("NIVON_GCS_BUCKET_PRIVADO_VERIFICADO")=="true"),
            executar=True)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
