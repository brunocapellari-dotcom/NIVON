"""Primeiro lancamento interno NIVON: readback BQ real e painel privado no GCS.

Sem criar tabelas, containers, IAM ou URLs publicas. Apenas 3 consultas
limitadas, 2 objetos pequenos em bucket existente, com precondicoes.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone,timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from nivon.painel_lancamento import construir_retrato, renderizar_html, ErroLancamento
from nivon.ponte_painel_fontes import analisar_fontes

PROJETO="nivon-data"
DATASET="nivon_raw"
BUCKET="nivon-data-raw-2026"
PREFIX="nivon/painel-interno"


def _corte(value):
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroLancamento("timestamp de corte invalido") from exc
    if dt.utcoffset() is None:
        raise ErroLancamento("corte sem timezone")
    return dt.astimezone(timezone.utc)


def consultas_do_lancamento(corte, *, projeto=PROJETO,dataset=DATASET):
    if projeto!=PROJETO or dataset!=DATASET:
        raise ErroLancamento("escopo Google Cloud diverge do NIVON")
    dt=_corte(corte)
    fim=dt.date()
    inicio=fim-timedelta(days=30)
    base={"projeto":projeto,"dataset":dataset,
          "inicio":inicio.isoformat(),"fim":fim.isoformat(),"limite":500}
    return {
        "ferrovia_bigquery":{
            "projeto":projeto,"dataset":dataset,
            "competencia":"2026-08","uf_origem":"MT"
        },
        "consultas_maritimas_bigquery":[
            {**base,"fonte":"imbituba"},
            {**base,"passagem":"panama"},
        ],
    }


def criar_produto(corte, *, leitor=analisar_fontes):
    corte=_corte(corte).isoformat()
    config=consultas_do_lancamento(corte)
    painel=leitor(config,as_of=corte,executar_bigquery=True)
    retrato=construir_retrato(painel,as_of=corte)
    html=renderizar_html(retrato)
    if len(html.encode("utf-8"))>250_000:
        raise ErroLancamento("painel excedeu limite de seguranca")
    payload=json.dumps(retrato,ensure_ascii=False,sort_keys=True,
                       separators=(",",":")).encode("utf-8")
    if len(payload)>50_000:
        raise ErroLancamento("JSON gerencial excedeu limite")
    return retrato,html.encode("utf-8"),payload


def _bucket_privado(bucket):
    """Falha se nao for possivel provar ausencia de acesso publico."""
    bucket.reload()
    pap=getattr(getattr(bucket,"iam_configuration",None),
                "public_access_prevention",None)
    if pap=="enforced":
        return True
    policy=bucket.get_iam_policy(requested_policy_version=3)
    bindings=policy.get("bindings",[]) if isinstance(policy,dict) else getattr(policy,"bindings",[])
    for binding in bindings:
        members=binding.get("members",[]) if isinstance(binding,dict) else getattr(binding,"members",[])
        if any(x in ("allUsers","allAuthenticatedUsers") for x in members):
            raise ErroLancamento("bucket apresenta membros IAM publicos")
    # Politica atual herdada pode exigir avaliacao adicional fora do bucket.
    if pap not in ("enforced",):
        raise ErroLancamento("bucket nao comprova Public Access Prevention enforced")
    return True


def publicar_no_gcs(*,bucket,html,payload,corte,storage_client=None):
    """Escreve snapshots imutaveis, sem sobrescrever aliases ou permissões.

    Sem URLs assinadas. Sem modificar ACL, IAM, lifecycle ou criar bucket.
    """
    if bucket!=BUCKET:
        raise ErroLancamento("bucket divergente")
    dt=_corte(corte)
    if len(html)>250_000 or len(payload)>50_000 or not html or not payload:
        raise ErroLancamento("payload de publicacao fora de limites")
    try:
        parsed=json.loads(payload)
    except ValueError as exc:
        raise ErroLancamento("snapshot JSON invalido") from exc
    if parsed.get("privacidade")!="INTERNO_PRIVADO":
        raise ErroLancamento("snapshot nao autorizado para entrega interna")
    if storage_client is None:
        from google.cloud import storage
        storage_client=storage.Client(project=PROJETO)
    target=storage_client.bucket(BUCKET)
    _bucket_privado(target)
    stamp=dt.strftime("%Y%m%dT%H%M%SZ")
    revision=sha256(payload).hexdigest()
    path=f"{PREFIX}/revisoes/{stamp}-{revision[:12]}"
    metadata={"nivon-classe":"INTERNO_PRIVADO",
              "nivon-sha256-json":revision,
              "nivon-data-corte":dt.isoformat()}
    files=[(path+".html",html,"text/html; charset=utf-8"),
           (path+".json",payload,"application/json; charset=utf-8")]
    # Conservar privilégio minimo storage.objects.create. Substituir latest
    # exigiria storage.objects.delete e NAO sera feito automaticamente.
    criados=0
    for name,body,mime in files:
        blob=target.blob(name)
        if blob.exists():
            # Retry idempotente: somente aceitar a mesma evidencia.
            if sha256(blob.download_as_bytes()).digest()!=sha256(body).digest():
                raise ErroLancamento("revisao GCS existente diverge do SHA")
            continue
        blob.cache_control="private, no-store, max-age=0"
        blob.metadata=metadata
        blob.upload_from_string(body,content_type=mime,if_generation_match=0)
        criados+=1
    # Readback de ambos: inclui objetos reutilizados de tentativa anterior.
    for name,body,_ in files:
        stored=target.blob(name).download_as_bytes()
        if sha256(stored).digest()!=sha256(body).digest():
            raise ErroLancamento("readback GCS nao corresponde a evidencia escrita")
    return {
        "status":"PUBLICADO_REVISAO_PRIVADA_GCS",
        "bucket":bucket,"prefixo":PREFIX,
        "objetos":len(files),"objetos_novos":criados,
        "revisao_html":files[0][0],"revisao_json":files[1][0],
        "data_corte":dt.isoformat(),"sha256_json":revision,
        "sem_url_publica":True,"sem_novos_recursos":True,
        "latest_atualizado":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: primeira edicao interna do painel")
    p.add_argument("--as-of",default=None)
    p.add_argument("--projeto",default=PROJETO)
    p.add_argument("--dataset",default=DATASET)
    p.add_argument("--bucket",default=BUCKET)
    p.add_argument("--executar",action="store_true",
                   help="ler Google Cloud e publicar GCS privado, pode consumir cota")
    opts=p.parse_args(argv)
    if (opts.projeto,opts.dataset,opts.bucket)!=(PROJETO,DATASET,BUCKET):
        raise ErroLancamento("escopo de lancamento incorreto")
    corte=opts.as_of or datetime.now(timezone.utc).isoformat()
    _corte(corte)
    if not opts.executar:
        print(json.dumps({
            "status":"PLANO_SEM_REDE",
            "consultas":consultas_do_lancamento(corte),
            "publicacao":PREFIX,
            "sem_efetuar_gasto_ou_escrita":True,
        },ensure_ascii=False))
        return 0
    retrato,html,payload=criar_produto(corte)
    status=publicar_no_gcs(bucket=opts.bucket,html=html,payload=payload,corte=corte)
    # Os dados agregados permanecem no GCS privado. Exibir somente status.
    print(json.dumps(status,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
