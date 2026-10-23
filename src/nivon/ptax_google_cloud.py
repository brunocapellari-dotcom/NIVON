"""Objetos GCS preparados a partir de quarentena PTAX, sem publicação.

Envio é OPCIONAL, requer autorização explícita de arquivo/armazenamento,
e cliente Google Cloud Storage autenticado. Sem ativação, não faz rede,
não depende de credenciais no CI e não cria buckets. A presença de
um objeto em GCS NÃO comprova origem BCB, licença de redistribuição
nem data de publicação.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
import sqlite3
from typing import Mapping

from .ptax_quarentena_coleta import (
    ErroQuarentenaPTAX, validar_amostra_ptax, ESTADO,
)


class ErroExportacaoPTAX(ValueError):
    """Exportação do raw PTAX bloqueada ou inconsistente."""


def preparar_objetos_gcs_ptax(
    db: sqlite3.Connection, *, evento_sha256: str,
    bucket: str, prefixo: str = "nivon/ptax/quarentena/v1",
) -> dict:
    """Retorna objetos e conteúdo exato; não faz chamadas Google Cloud."""
    if not isinstance(db, sqlite3.Connection):
        raise ErroExportacaoPTAX("SQLite obrigatório")
    if not isinstance(evento_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", evento_sha256
    ):
        raise ErroExportacaoPTAX("identificador de evento inválido")
    if not isinstance(bucket, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{2,62}", bucket
    ):
        raise ErroExportacaoPTAX("bucket inválido ou não canônico")
    if not isinstance(prefixo, str) or not re.fullmatch(
        r"[a-z0-9_-]+(?:/[a-z0-9_-]+){0,7}", prefixo
    ):
        raise ErroExportacaoPTAX("prefixo perigoso/inválido")
    try:
        row = db.execute(
            "SELECT e.raw_sha256,e.manifesto_json,e.qt_boletins,"
            "e.status,b.raw FROM nivon_ptax_quarentena_eventos e "
            "JOIN nivon_ptax_quarentena_raw b ON b.raw_sha256=e.raw_sha256 "
            "WHERE e.evento_sha256=?",
            (evento_sha256,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise ErroExportacaoPTAX("quarentena inacessível") from exc
    if row is None:
        raise ErroExportacaoPTAX("evento de captura inexistente")
    digest, manifest_json, qt, status, raw = row
    if status != ESTADO or not isinstance(raw, bytes) or (
        sha256(raw).hexdigest() != digest
    ):
        raise ErroExportacaoPTAX("raw adulterado ou estado incompatível")
    try:
        manifesto = json.loads(manifest_json)
        prova = validar_amostra_ptax(raw, manifesto)
    except (ValueError, TypeError) as exc:
        raise ErroExportacaoPTAX("metadata inválida") from exc
    if prova["evento_sha256"] != evento_sha256 or prova["boletins"] != qt:
        raise ErroExportacaoPTAX("evento diverge do manifesto")
    metadata_bytes = json.dumps({
        "estado": ESTADO,
        "origem_independente_comprovada": False,
        "publicacao_independente_comprovada": False,
        "raw_sha256": digest, "evento_sha256": evento_sha256,
        "qt_boletins": qt,
        "manifesto_canonico": prova["manifesto_canonico"],
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    objetos = [
        {
            "chave": f"{prefixo}/raw/{digest}.json",
            "mime": "application/json",
            "sha256": digest,
            "bytes": raw,
        }, {
            "chave": f"{prefixo}/manifestos/{evento_sha256}.json",
            "mime": "application/json",
            "sha256": sha256(metadata_bytes).hexdigest(),
            "bytes": metadata_bytes,
        },
    ]
    return {
        "status": "EXPORTACAO_GCS_PREPARADA_SEM_ENVIO",
        "bucket": bucket, "prefixo": prefixo,
        "objetos": objetos,
        "total_bytes": sum(len(x["bytes"]) for x in objetos),
        "direitos_revisados_por_este_modulo": False,
        "upload_executado": False, "publicavel": False,
    }


def enviar_objetos_gcs_ptax(
    pacote: Mapping, *, permitir_upload: bool = False,
    referencia_direitos: str | None = None,
    referencia_custo: str | None = None,
    cliente=None,
) -> dict:
    """Envia objetos GCS imutáveis com precondição generation=0.

    Somente Cloud Storage SDK instalado em ambiente autorizado.
    Nenhum retry automático ou overwrite. Cada operação pode ser
    faturável; não iniciar sem aprovação concreta de custo.
    """
    if not isinstance(pacote, Mapping) or (
        pacote.get("status") != "EXPORTACAO_GCS_PREPARADA_SEM_ENVIO"
    ):
        raise ErroExportacaoPTAX("pacote não preparado")
    if not permitir_upload:
        raise PermissionError("upload Google Cloud desabilitado por padrão")
    if not all(isinstance(x, str) and 8 <= len(x) <= 150 and
               re.fullmatch(r"[A-Za-z0-9_./:-]+", x)
               for x in (referencia_direitos, referencia_custo)):
        raise PermissionError("faltam referências explícitas de direitos e orçamento")
    if not isinstance(pacote.get("objetos"), list) or len(pacote["objetos"]) != 2:
        raise ErroExportacaoPTAX("objetos de GCS inválidos")
    bucket_nome = pacote.get("bucket")
    prefixo = pacote.get("prefixo")
    if (not isinstance(bucket_nome, str) or not re.fullmatch(
            r"[a-z][a-z0-9-]{2,62}", bucket_nome
    ) or not isinstance(prefixo, str) or not re.fullmatch(
            r"[a-z0-9_-]+(?:/[a-z0-9_-]+){0,7}", prefixo
    )):
        raise ErroExportacaoPTAX("destino GCS modificado ou inválido")
    raw_obj, manifest_obj = pacote["objetos"]
    if any(not isinstance(x, Mapping) or set(x) != {
        "chave", "mime", "sha256", "bytes"
    } for x in (raw_obj, manifest_obj)):
        raise ErroExportacaoPTAX("objeto GCS fora do contrato")
    if any(type(x["bytes"]) is not bytes or
           len(x["bytes"]) > 2_500_000 or
           not isinstance(x["sha256"], str) or
           sha256(x["bytes"]).hexdigest() != x["sha256"] or
           x["mime"] != "application/json"
           for x in (raw_obj, manifest_obj)):
        raise ErroExportacaoPTAX("objeto GCS adulterado ou excessivo")
    try:
        meta = json.loads(manifest_obj["bytes"])
        evento = meta["evento_sha256"]
        if (not isinstance(evento, str) or not re.fullmatch(
                r"[0-9a-f]{64}", evento
        ) or meta["estado"] != ESTADO or
            meta["raw_sha256"] != raw_obj["sha256"] or
            meta["origem_independente_comprovada"] is not False or
            meta["publicacao_independente_comprovada"] is not False):
            raise ErroExportacaoPTAX("proveniência de objeto GCS incoerente")
        if raw_obj["chave"] != f"{prefixo}/raw/{raw_obj['sha256']}.json" or (
            manifest_obj["chave"] != f"{prefixo}/manifestos/{evento}.json"
        ):
            raise ErroExportacaoPTAX("chaves de armazenamento fora do contrato")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ErroExportacaoPTAX):
            raise
        raise ErroExportacaoPTAX("manifesto GCS adulterado") from exc
    if cliente is None:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise ErroExportacaoPTAX("google-cloud-storage não instalado") from exc
        cliente = storage.Client()
    try:
        bucket = cliente.bucket(pacote["bucket"])
        resultados = []
        for objeto in pacote["objetos"]:
            if not isinstance(objeto, Mapping) or (
                sha256(objeto["bytes"]).hexdigest() != objeto["sha256"]
            ):
                raise ErroExportacaoPTAX("conteúdo de upload adulterado")
            blob = bucket.blob(objeto["chave"])
            blob.upload_from_string(
                objeto["bytes"], content_type=objeto["mime"],
                if_generation_match=0, timeout=30,
            )
            resultados.append({
                "uri": f"gs://{pacote['bucket']}/{objeto['chave']}",
                "sha256": objeto["sha256"],
                "bytes": len(objeto["bytes"]),
            })
    except ErroExportacaoPTAX:
        raise
    except Exception as exc:
        # Falha parcial pode ter criado o primeiro objeto. Condição GCS
        # generation=0 impede substituição; reconciliar, nunca sobrescrever.
        raise ErroExportacaoPTAX(
            "upload GCS incompleto; reconciliar objetos antes de nova tentativa"
        ) from exc
    return {
        "status": "OBJETOS_ARQUIVADOS_GCS_SEM_HOMOLOGACAO_EDITORIAL",
        "objetos": resultados, "quantidade": len(resultados),
        "direitos_de_redistribuicao_verificados": False,
        "publicavel": False,
    }
