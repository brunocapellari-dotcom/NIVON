"""NIVON CONAB — arquivamento imutável de XLSX e evidências no GCS.

Usa o bucket NIVON PREEXISTENTE, dados privados autorizados e ADC/WIF.
Não cria projeto, bucket, IAM, Cloud Run ou agendamentos. Por padrão
gera apenas preflight local. A confirmação de GCS exige readback SHA256.

Cada edição e revisão RAW recebe namespace próprio. Reprocessamento
por SHA é idempotente; nunca substitui uma versão anterior.
"""
from __future__ import annotations

from datetime import datetime,timezone
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from .captura_xlsx_conab import RAW_FILE,EVIDENCE_FILE,verificar_pacote_captura_local
from .conab_resolver_anexo import montar_registro_captura


class ErroArquivoConabGCS(ValueError):
    pass


BUCKET=re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
_SHA=re.compile(r"^[a-f0-9]{64}$")
MAX_BYTES=20_000_000
PREFIXO="nivon/conab/progresso/v1"


def _privado(path:Path,*,diretorio:bool):
    if path.is_symlink() or not (path.is_dir() if diretorio else path.is_file()):
        raise ErroArquivoConabGCS("arquivo/diretorio privado ausente ou simbolico")
    if os.name=="posix" and stat.S_IMODE(path.stat().st_mode)&0o077:
        raise ErroArquivoConabGCS("arquivo ou diretorio acessivel a terceiros")


def preparar_lote(*,banco:str|Path,raw_dir:str|Path,bucket:str)->dict:
    """Lê e valida pacotes locais sem tocar GCP, respeitando hashes reais."""
    if not isinstance(bucket,str) or not BUCKET.fullmatch(bucket) or ".." in bucket:
        raise ErroArquivoConabGCS("nome do bucket invalido")
    bank=Path(banco)
    root=Path(raw_dir)
    _privado(bank,diretorio=False)
    _privado(root,diretorio=True)
    items=[]
    db=sqlite3.connect("file:"+bank.resolve().as_posix()+"?mode=ro",uri=True)
    db.row_factory=sqlite3.Row
    try:
        sql="""SELECT s.pagina_url,s.periodo_rotulo,s.titulo,
                      a.url_documento,a.url_anexo,a.pagina_publicada_data,
                      a.hash_html_documento,a.primeira_coleta_utc
               FROM conab_anexos_resolvidos a
               JOIN conab_semanas_descobertas s ON s.pagina_url=a.pagina_semana
               ORDER BY s.pagina_url,a.url_documento"""
        for row in db.execute(sql):
            page=row["pagina_url"]
            resolved={"pagina_semana":page,"url_documento":row["url_documento"],
                "url_anexo":row["url_anexo"],
                "publicacao_data":row["pagina_publicada_data"],
                "hash_html_documento":row["hash_html_documento"],
                "coletado_em_utc":row["primeira_coleta_utc"],
                "estado":"LINK_XLSX_DESCOBERTO_NAO_BAIXADO"}
            edition={"pagina_oficial":page,"titulo":row["titulo"],
                     "periodo_rotulo":row["periodo_rotulo"]}
            reg=montar_registro_captura(indice_semana=edition,resolucao=resolved)
            folder=root/(reg["id_edicao"]+"_"+sha256(reg["url_anexo"].encode()).hexdigest()[:16])
            if not folder.exists():
                continue
            _privado(folder,diretorio=True)
            checked=verificar_pacote_captura_local(reg,folder)
            digest=checked["sha256"]
            if not _SHA.fullmatch(digest):
                raise ErroArquivoConabGCS("SHA de XLSX nao reconhecido")
            raw=folder/RAW_FILE
            ev=folder/EVIDENCE_FILE
            _privado(raw,diretorio=False)
            _privado(ev,diretorio=False)
            if raw.stat().st_size>MAX_BYTES or ev.stat().st_size>100_000:
                raise ErroArquivoConabGCS("arquivo muito grande")
            meta=json.loads(ev.read_text(encoding="utf-8"))
            if (meta.get("bytes_sha256")!=digest or
                    meta.get("url_anexo")!=reg["url_anexo"] or
                    meta.get("id_edicao")!=reg["id_edicao"]):
                raise ErroArquivoConabGCS("evidencia local nao corresponde ao pacote")
            prefix=f"{PREFIXO}/{reg['id_edicao']}/{digest}"
            items.append({"id_edicao":reg["id_edicao"],"sha256_raw":digest,
                          "publicacao_data":reg["publicacao_data"],
                          "url_origem":reg["url_anexo"],
                          "coletado_utc":meta["transport_evidencia"]["finalizado_utc"],
                          "observacoes":checked["observacoes"],
                          "raw":str(raw),"evidencia":str(ev),
                          "uri_raw":f"gs://{bucket}/{prefix}/raw.xlsx",
                          "uri_evidencia":f"gs://{bucket}/{prefix}/evidencia.json"})
            if len(items)>10:
                raise ErroArquivoConabGCS("limite de 10 edicoes por lote")
    finally:
        db.close()
    if not items:
        raise ErroArquivoConabGCS("nenhum XLSX CONAB real verificavel para arquivar")
    return {"status":"PREFLIGHT_LOCAL_GCS_SEM_ESCRITA","bucket":bucket,
            "edicoes":items,"total_edicoes":len(items),"cloud_gravado":False}


def _guardar(bucket,uri:str,data:bytes,*,sha:str,mime:str,metadata:dict,
             precondition_failed=None):
    prefix=f"gs://{bucket.name}/"
    if not uri.startswith(prefix):
        raise ErroArquivoConabGCS("URI fora do bucket")
    path=uri[len(prefix):]
    if not path.startswith(PREFIXO+"/") or any(p in (".","..","") for p in path.split("/")):
        raise ErroArquivoConabGCS("caminho GCS fora do prefixo")
    blob=bucket.blob(path)
    blob.metadata={"sha256":sha,**metadata}
    try:
        blob.upload_from_string(data,content_type=mime,if_generation_match=0)
    except Exception as exc:
        if precondition_failed is None or not isinstance(exc,precondition_failed):
            raise
        # Somente "precondition failed" autorizado para replay da mesma versão.
        blob.reload()
        if (blob.metadata or {}).get("sha256")!=sha:
            raise ErroArquivoConabGCS("objeto existente diverge da versao original") from exc
    blob.reload()
    if (blob.metadata or {}).get("sha256")!=sha:
        raise ErroArquivoConabGCS("GCS nao reteve o SHA esperado")
    # Readback imediato: prova bytes preservados, nao só sucesso do upload.
    retornado=blob.download_as_bytes()
    if sha256(retornado).hexdigest()!=sha or len(retornado)!=len(data):
        raise ErroArquivoConabGCS("readback GCS nao confirmou os bytes")
    return {"uri":uri,"sha256":sha,"bytes":len(data)}


def arquivar_lote(*,banco:str|Path,raw_dir:str|Path,bucket:str,
                  executar:bool=False,direitos_armazenamento:bool=False,
                  custos_autorizados:bool=False,cliente=None,
                  precondition_failed=None)->dict:
    plano=preparar_lote(banco=banco,raw_dir=raw_dir,bucket=bucket)
    if not executar:
        return {"status":plano["status"],"total_edicoes":plano["total_edicoes"],
                "bucket":bucket,"cloud_gravado":False}
    if direitos_armazenamento is not True or custos_autorizados is not True:
        raise PermissionError("GCS requer aprovacao explicita de direitos e custos")
    if cliente is None:
        from google.cloud import storage
        cliente=storage.Client()
    if precondition_failed is None:
        from google.api_core.exceptions import PreconditionFailed
        precondition_failed=PreconditionFailed
    # Apenas recuperar bucket existente; sem create_bucket nem setIamPolicy.
    destino=cliente.get_bucket(bucket)
    if str(destino.location or "").lower()!="southamerica-east1":
        raise ErroArquivoConabGCS("bucket nao esta na regiao NIVON")
    salvos=[]
    for item in plano["edicoes"]:
        raw=Path(item["raw"]).read_bytes()
        evidencia=Path(item["evidencia"]).read_bytes()
        if sha256(raw).hexdigest()!=item["sha256_raw"]:
            raise ErroArquivoConabGCS("RAW mudou depois do preflight")
        meta={"fonte":"CONAB","edicao":item["id_edicao"],
              "coleta":item["coletado_utc"]}
        raw_item=_guardar(destino,item["uri_raw"],raw,sha=item["sha256_raw"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            metadata=meta,precondition_failed=precondition_failed)
        ev_item=_guardar(destino,item["uri_evidencia"],evidencia,
            sha=sha256(evidencia).hexdigest(),mime="application/json",
            metadata=meta,precondition_failed=precondition_failed)
        salvos.append({"id_edicao":item["id_edicao"],
                       "raw":raw_item,"evidencia":ev_item,
                       "observacoes":item["observacoes"]})
    return {"status":"RAW_CONAB_IMUTAVEL_GCS_COM_READBACK",
            "total_edicoes":len(salvos),"edicoes":salvos,
            "cloud_gravado":True,"bigquery_gravado":False,
            "publicacao_permitida":False}


def main():
    p=argparse.ArgumentParser(description="NIVON CONAB: arquivar XLSX em GCS existente")
    p.add_argument("--banco",required=True)
    p.add_argument("--pasta-raw",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--executar",action="store_true")
    p.add_argument("--direitos-armazenamento",action="store_true")
    p.add_argument("--custos-autorizados",action="store_true")
    a=p.parse_args()
    result=arquivar_lote(banco=a.banco,raw_dir=a.pasta_raw,
        bucket=a.bucket,executar=a.executar,
        direitos_armazenamento=a.direitos_armazenamento,
        custos_autorizados=a.custos_autorizados)
    # Apenas metadados, paths de objetos e SHA; nenhum XLSX no stdout.
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
