"""Reconciliação de leitura GCS: comprova igualdade com pacote LOCAL, não BCB.

Não altera objetos. As leituras podem ter custo: necessitam flag opt-in
e referência de orçamento. Nunca declara autenticidade da fonte, nem
certifica tempo de publicação e direito de redistribuição.
"""
from __future__ import annotations

from hashlib import sha256
import re
from typing import Mapping

from .ptax_google_cloud import ErroExportacaoPTAX


def reconciliar_gcs_ptax(
    pacote: Mapping, *, cliente=None,
    permitir_leitura: bool = False, referencia_custo: str | None = None,
) -> dict:
    if not isinstance(pacote, Mapping) or (
        pacote.get("status") != "EXPORTACAO_GCS_PREPARADA_SEM_ENVIO"
    ):
        raise ErroExportacaoPTAX("pacote GCS inválido")
    if not permitir_leitura:
        raise PermissionError("leitura GCS desabilitada por padrão")
    if not isinstance(referencia_custo, str) or not (
        8 <= len(referencia_custo) <= 150
    ) or not re.fullmatch(r"[A-Za-z0-9_./:-]+", referencia_custo):
        raise PermissionError("referência de orçamento necessária")
    bucket_nome = pacote.get("bucket")
    prefixo = pacote.get("prefixo")
    if not isinstance(bucket_nome, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{2,62}", bucket_nome
    ) or not isinstance(prefixo, str) or not re.fullmatch(
        r"[a-z0-9_-]+(?:/[a-z0-9_-]+){0,7}", prefixo
    ):
        raise ErroExportacaoPTAX("destino GCS adulterado")
    objetos = pacote.get("objetos")
    if not isinstance(objetos, list) or len(objetos) != 2:
        raise ErroExportacaoPTAX("objetos GCS inválidos")
    esperado = {}
    for i, objeto in enumerate(objetos):
        if not isinstance(objeto, Mapping) or set(objeto) != {
            "chave","mime","sha256","bytes"
        }:
            raise ErroExportacaoPTAX("contrato de objeto inválido")
        if type(objeto["bytes"]) is not bytes or not (
            1 <= len(objeto["bytes"]) <= 2_500_000
        ) or not isinstance(objeto["sha256"], str) or (
            sha256(objeto["bytes"]).hexdigest() != objeto["sha256"]
        ) or objeto["mime"] != "application/json":
            raise ErroExportacaoPTAX("objeto local adulterado")
        parte = "raw" if i == 0 else "manifestos"
        if parte == "raw":
            key = f"{prefixo}/raw/{objeto['sha256']}.json"
        else:
            try:
                import json
                meta = json.loads(objeto["bytes"])
                evt = meta["evento_sha256"]
            except (ValueError, KeyError, TypeError) as exc:
                raise ErroExportacaoPTAX("manifesto GCS inválido") from exc
            if not isinstance(evt, str) or not re.fullmatch(
                r"[a-f0-9]{64}", evt
            ) or meta.get("raw_sha256") != objetos[0]["sha256"] or (
                meta.get("origem_independente_comprovada") is not False
            ) or meta.get("publicacao_independente_comprovada") is not False:
                raise ErroExportacaoPTAX("manifesto GCS não corresponde ao raw")
            key = f"{prefixo}/manifestos/{evt}.json"
        if objeto["chave"] != key or key in esperado:
            raise ErroExportacaoPTAX("chave GCS não canônica")
        esperado[key] = objeto
    if cliente is None:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise ErroExportacaoPTAX("google-cloud-storage indisponível") from exc
        cliente = storage.Client()
    bucket = cliente.bucket(bucket_nome)
    resultados = []
    for chave, objeto in esperado.items():
        blob = bucket.blob(chave)
        try:
            existe = blob.exists()
            if existe is False:
                resultados.append({"chave": chave, "estado":"AUSENTE"})
                continue
            arquivo = blob.download_as_bytes(timeout=30)
        except Exception as exc:
            # Erro de IAM/rede não deve ser confundido com inexistência.
            raise ErroExportacaoPTAX(
                "falha de acesso GCS; não foi possível reconciliar"
            ) from exc
        if type(arquivo) is not bytes or sha256(arquivo).hexdigest() != (
            objeto["sha256"]
        ) or len(arquivo) != len(objeto["bytes"]) or (
            arquivo != objeto["bytes"]
        ):
            resultados.append({"chave": chave, "estado":"DIVERGENTE"})
        else:
            resultados.append({"chave": chave, "estado":"CONFERIDO"})
    completo = all(x["estado"] == "CONFERIDO" for x in resultados)
    return {
        "status": ("ARQUIVO_GCS_RECONCILIADO_OFFLINE_SEM_HOMOLOGACAO"
                   if completo else "ARQUIVO_GCS_INCOMPLETO_OU_DIVERGENTE"),
        "total":len(resultados),
        "objetos_conferidos":sum(x["estado"] == "CONFERIDO" for x in resultados),
        "objetos_ausentes":sum(x["estado"] == "AUSENTE" for x in resultados),
        "objetos_divergentes":sum(x["estado"] == "DIVERGENTE" for x in resultados),
        "resultados":resultados,
        "integridade_bytes_gcs_local_confirmada": completo,
        "origem_bcb_independente_confirmada":False,
        "publicavel":False,
    }
