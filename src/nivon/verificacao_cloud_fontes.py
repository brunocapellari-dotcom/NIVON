"""NIVON: leitura de confirmação pós-carga GCS e BigQuery.

Controle obrigatório: nenhum sucesso de pipeline sem conferir que amostras reais
estão acessíveis nos dois destinos. A leitura BigQuery é pequena/limitada e
requer tabela particionada por data_referencia.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from .arquivo_raw_gcs import preparar_manifesto, ErroArquivoCloud
from .carga_bigquery_fontes import planejar_carga, ErroCargaBigQuery, PROJECT, DATASET


class ErroVerificacaoCloud(ValueError):
    pass


def _amostras_jsonl(arquivo, project_id, dataset_id):
    contrato = planejar_carga(
        arquivo=arquivo,project_id=project_id,dataset_id=dataset_id)
    total = contrato["linhas"]
    if total <= 0:
        raise ErroVerificacaoCloud("lote analitico vazio")
    # Primeiro e último por dataset; não usar amostras artificiais ou dados
    # que não pertencem ao JSONL validado pelo loader.
    grupos = {}
    with Path(arquivo).open(encoding="utf-8") as f:
        for line in f:
            r=json.loads(line)
            origem=r["dataset_id"]
            if not isinstance(origem,str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,90}",origem):
                raise ErroVerificacaoCloud("dataset do registro invalido")
            identificador=(origem,r["fingerprint"],r["referencia"])
            if origem not in grupos:
                grupos[origem]=[identificador]
            elif len(grupos[origem])==1:
                if identificador != grupos[origem][0]:
                    grupos[origem].append(identificador)
            else:
                grupos[origem][-1]=identificador
    if not 1 <= len(grupos) <= 15:
        raise ErroVerificacaoCloud("numero de datasets por carga nao autorizado")
    encontrados=sorted({x for grupo in grupos.values() for x in grupo})
    return encontrados,contrato


def verificar_publicacao(*, banco, raw_dir, bucket, arquivo_jsonl,
                        project_id, dataset_id, executar=False,
                        client_storage=None, client_bq=None,
                        max_bytes_billed=100_000_000):
    """Verifica todos os metadados RAW, conteúdo de 1 snapshot e BQ samples.

    Leitura sem alterações no destino; toda inconsistência encerra com erro.
    """
    manifesto=preparar_manifesto(banco=banco,raw_dir=raw_dir,bucket=bucket)
    samples,contrato=_amostras_jsonl(arquivo_jsonl,project_id,dataset_id)
    if type(max_bytes_billed) is not int or not 10_000_000<=max_bytes_billed<=100_000_000:
        raise ErroVerificacaoCloud("limite de cobrança/verificação inválido")
    plan={"bucket":bucket,"objetos_raw":manifesto["quantidade"],
          "amostras_bigquery":len(samples),"linhas_jsonl":contrato["linhas"],
          "projeto":project_id,"dataset":dataset_id,"executado":False}
    if executar is not True:
        return plan
    try:
        from google.cloud import bigquery, storage
    except ImportError as exc:
        raise RuntimeError("instale NIVON[gcp] para verificação real") from exc

    sc=client_storage if client_storage is not None else storage.Client(project=project_id)
    bc=client_bq if client_bq is not None else bigquery.Client(project=project_id)
    recipiente=sc.bucket(bucket)
    for item in manifesto["objetos"]:
        remote=recipiente.get_blob(item["objeto"])
        if (remote is None or remote.size!=item["bytes"] or
            not isinstance(remote.metadata,dict) or
            remote.metadata.get("sha256")!=item["sha256"] or
            remote.metadata.get("snapshot_id")!=item["snapshot_id"]):
            raise ErroVerificacaoCloud("RAW nao encontrado/identidade invalida no GCS")
    # Confrontar bytes de pelo menos 1 arquivo bruto, além de metadados.
    primeiro=manifesto["objetos"][0]
    blob=recipiente.get_blob(primeiro["objeto"])
    try:
        bruto=blob.download_as_bytes(timeout=90)
    except Exception as exc:
        raise ErroVerificacaoCloud("impossivel verificar bytes GCS") from exc
    if not isinstance(bruto,bytes) or hashlib.sha256(bruto).hexdigest()!=primeiro["sha256"]:
        raise ErroVerificacaoCloud("conteudo RAW do GCS difere do SHA original")

    # Uma query parametrizada, data_referencia é coluna de partição (preflight).
    # Por segurança, limita a 30 fingerprints e 15 datasets por job.
    refs=sorted({r[2] for r in samples})
    start=date.fromisoformat(refs[0])
    end=date.fromisoformat(refs[-1])
    names=sorted({r[0] for r in samples})
    fingerprints=sorted({r[1] for r in samples})
    sql=(
        f"SELECT dataset_id, fingerprint, CAST(data_referencia AS STRING) referencia "
        f"FROM `{project_id}.{dataset_id}.nivon_observacoes` "
        f"WHERE data_referencia BETWEEN @inicio AND @fim "
        f"AND dataset_id IN UNNEST(@ids) "
        f"AND fingerprint IN UNNEST(@hashes)"
    )
    config=bigquery.QueryJobConfig(
        maximum_bytes_billed=max_bytes_billed,
        query_parameters=[
            bigquery.ScalarQueryParameter("inicio","DATE",start),
            bigquery.ScalarQueryParameter("fim","DATE",end),
            bigquery.ArrayQueryParameter("ids","STRING",names),
            bigquery.ArrayQueryParameter("hashes","STRING",fingerprints),
        ],
    )
    try:
        result=bc.query(sql,job_config=config).result(timeout=90)
        vistos={(str(row["dataset_id"]),str(row["fingerprint"]),
                str(row["referencia"])) for row in result}
    except Exception as exc:
        raise ErroVerificacaoCloud("consulta de confirmacao BigQuery falhou") from exc
    esperados=set(samples)
    if not esperados.issubset(vistos):
        raise ErroVerificacaoCloud(
            f"BigQuery sem todas as amostras: presentes={len(esperados & vistos)}/{len(esperados)}"
        )
    return {**plan,"executado":True,"objetos_gcs_confirmados":manifesto["quantidade"],
            "raw_byte_sha_validado":primeiro["sha256"],
            "amostras_bigquery_confirmadas":len(esperados),
            "publicacao_operacional":"ARQUIVAMENTO_E_CONSULTA_CONFIRMADOS",
            "dados_publicados_externamente":False}


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: verificar pós-carga Google Cloud")
    p.add_argument("--banco",required=True)
    p.add_argument("--raw-dir",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--arquivo",required=True)
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--executar",action="store_true")
    a=p.parse_args(argv)
    resposta=verificar_publicacao(
       banco=a.banco,raw_dir=a.raw_dir,bucket=a.bucket,arquivo_jsonl=a.arquivo,
       project_id=a.projeto,dataset_id=a.dataset,executar=a.executar)
    print(json.dumps(resposta,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
