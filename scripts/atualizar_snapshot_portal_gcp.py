"""Uma execução autorizada: BigQuery real -> leitura privada GCS, sem deploy.

Nenhuma chamada remota em import. Requer WIF/ADC, IAM mínimo, orçamento
aprovado pelo executor e fonte com permissão de uso interno.
"""
from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
import re

from nivon.ponte_painel_fontes import analisar_fontes
from nivon.portal_interno import montar_snapshot, validar_snapshot, ErroPortal

ARQUIVO_PRIVADO="interno/nivon/portal/v1/painel.json"


def planejar(*, projeto, dataset, bucket, competencia, agora):
    if (projeto!="nivon-data" or dataset!="nivon_raw"
            or bucket!="nivon-data-raw-2026"
            or not isinstance(competencia,str)
            or not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])",competencia)):
        raise ErroPortal("destino cloud ou competencia divergente")
    if not isinstance(agora,datetime) or agora.utcoffset() is None:
        raise ErroPortal("relogio timezone-aware obrigatorio")
    utc=agora.astimezone(timezone.utc)
    if competencia>utc.strftime("%Y-%m"):
        raise ErroPortal("competencia ferroviaria futura")
    today=utc.date()
    opts={"projeto":projeto,"dataset":dataset,"inicio":today.replace(day=1).isoformat(),
          "fim":today.isoformat(),"limite":300}
    return {
        "as_of":utc.isoformat(timespec="seconds"),
        "consulta":{
            "ferrovia_bigquery":{"projeto":projeto,"dataset":dataset,
                                 "competencia":competencia,"uf_origem":"MT"},
            "consultas_maritimas_bigquery":[{**opts,"fonte":"imbituba"},
                                            {**opts,"passagem":"panama"}],
        },
        "objeto_privado":ARQUIVO_PRIVADO,
    }


def executar(*, projeto, dataset, bucket, competencia,
             analisar=analisar_fontes, storage_factory=None, agora=None):
    agora=datetime.now(timezone.utc) if agora is None else agora
    plano=planejar(projeto=projeto,dataset=dataset,bucket=bucket,
                   competencia=competencia,agora=agora)
    readback=analisar(plano["consulta"],as_of=plano["as_of"],executar_bigquery=True)
    doc=validar_snapshot(montar_snapshot(readback,gerado_em=plano["as_of"]))
    if (doc["publicavel"] is not False or doc["redistribuicao_autorizada"] is not False
            or doc["go_live_publico"] is not False):
        raise ErroPortal("snapshot excedeu o escopo interno")
    raw=json.dumps(doc,ensure_ascii=False,sort_keys=True,
                   separators=(",",":")).encode("utf-8")
    if len(raw)>2_000_000:
        raise ErroPortal("snapshot fora de limite")
    if storage_factory is None:
        from google.cloud import storage
        from google.api_core.exceptions import NotFound
        storage_factory=storage.Client
    else:
        # Permite E2E estritamente offline com storage injetado, sem SDK GCP.
        NotFound=FileNotFoundError
    cli=storage_factory(project=projeto)
    b=cli.get_bucket(bucket)
    if str(b.location).lower()!="southamerica-east1":
        raise ErroPortal("regiao GCS diferente")
    blob=b.blob(plano["objeto_privado"])
    try:
        blob.reload()
        generation=blob.generation
    except NotFound:
        generation=0
    digest=sha256(raw).hexdigest()
    blob.cache_control="private, no-store"
    blob.metadata={"nivon_modo":"INTERNO_SHADOW","sha256":digest}
    blob.upload_from_string(raw,content_type="application/json",
                            if_generation_match=generation,checksum="crc32c")
    # Sem readback da origem, não dizer que houve publicação consolidada.
    if sha256(blob.download_as_bytes()).hexdigest()!=digest:
        raise ErroPortal("readback SHA-256 do objeto falhou")
    return {"status":"SNAPSHOT_PRIVADO_GCS_VERIFICADO",
            "fontes":len(doc["fontes_consultadas"]),
            "indicadores_em_revisao":len(doc["indicadores"]),
            "publicavel":False,"readback_sha256_ok":True}


def main():
    if any(os.environ.get(k)!="true" for k in (
        "NIVON_PORTAL_GCP_READ_APPROVED",
        "NIVON_PORTAL_GCS_WRITE_APPROVED",
        "NIVON_PORTAL_PRIVATE_BUCKET_REVIEWED",
        "NIVON_ZERO_COST_BQ_APPROVED",
        "NIVON_RAW_ARCHIVE_APPROVED",
    )):
        raise SystemExit("PORTAL_GCP_GATE_NAO_APROVADO")
    try:
        out=executar(projeto=os.environ["NIVON_BQ_PROJECT"],
             dataset=os.environ["NIVON_BQ_DATASET"],
             bucket=os.environ["NIVON_GCS_BUCKET"],
             competencia=os.environ.get("NIVON_PORTAL_FERROVIA_COMPETENCIA","2026-08"))
    except (KeyError,ValueError,ImportError):
        raise SystemExit("PORTAL_GCP_COLETA_OU_READBACK_BLOQUEADO") from None
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
