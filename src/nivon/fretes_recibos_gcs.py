"""Adaptador GCS OPCIONAL para recibos de frete, SEM ativação no projeto.

Cliente/bucket do google-cloud-storage é injetado pelo runtime autorizado.
if_generation_match=0 bloqueia sobrescrita de objetos vivos; leitura da
geração exata verifica o upload. Não cria projeto, bucket, serviços ou
custos. Retenção, WORM, IAM, orçamento e horário independente NÃO atestados.
"""
from __future__ import annotations

from hashlib import sha256
import hmac
import re
from typing import Mapping

from .fretes_atestacoes import serializacao_canonica
from .fretes_recibos_ancora import (
    CAMPOS, VERSAO, ErroReciboFrete,
    verificar_recibo_local_frete,
)


class ErroReciboGCS(ErroReciboFrete):
    """Contrato Cloud Storage inseguro, leitura divergente ou escrita falha."""


_OBJ_RE=re.compile(r"^nivon/fretes/recibos/v1/(?:OFERTAS|PREVISOES)/[0-9]{9}_[0-9a-f]{32}\.json$")


def _destino(recibo: Mapping) -> str:
    if not isinstance(recibo,Mapping) or set(recibo)!=CAMPOS:
        raise ErroReciboGCS("recibo fora do contrato")
    if recibo["versao"]!=VERSAO or recibo["tipo_ledger"] not in ("OFERTAS","PREVISOES"):
        raise ErroReciboGCS("versão ou tipo não permitido")
    num=recibo["sequencia"]
    nonce=recibo["nonce_hex"]
    if type(num) is not int or not 1<=num<=1_000_000:
        raise ErroReciboGCS("sequência inválida")
    if not isinstance(nonce,str) or not re.fullmatch(r"[0-9a-f]{32}",nonce):
        raise ErroReciboGCS("nonce inválido")
    return f"nivon/fretes/recibos/v1/{recibo['tipo_ledger']}/{num:09d}_{nonce}.json"


def gravar_recibo_gcs_condicional(
    bucket, recibo: Mapping, *,
    chave_recibo: bytes, emissor_esperado: str, as_of,
    autorizar_escrita: bool = False,
) -> dict:
    """Executa gravação somente com bucket INJETADO e opt-in explícito.

    Nenhuma chamada externa ocorre quando autorizar_escrita=False.
    Um bucket Google Cloud Storage ativo poderá gerar custos por operações,
    armazenamento, rede e soft delete; cabe ao operador aprovar antes.
    """
    if autorizar_escrita is not True:
        return {
            "status":"GCS_DESABILITADO_POR_PADRAO",
            "tentativa_de_escrita":False,
            "publicavel":False,
        }
    ver=verificar_recibo_local_frete(
        recibo,chave_recibo=chave_recibo,as_of=as_of,
        tipo_esperado=recibo.get("tipo_ledger") if isinstance(recibo,Mapping) else "",
        emissor_esperado=emissor_esperado,
    )
    nome=_destino(recibo)
    dados=serializacao_canonica(dict(recibo))
    if len(dados)>8192:
        raise ErroReciboGCS("recibo GCS acima do limite")
    if (bucket is None or not isinstance(getattr(bucket,"name",None),str)
            or not bucket.name or not callable(getattr(bucket,"blob",None))):
        raise ErroReciboGCS("bucket GCS explícito e válido obrigatório")
    try:
        blob=bucket.blob(nome)
        # Pré-condição nativa GCS: somente se NÃO houver geração viva.
        blob.upload_from_string(
            dados,content_type="application/json",
            if_generation_match=0,timeout=15,
        )
        geracao=getattr(blob,"generation",None)
        if type(geracao) not in (int,str) or not str(geracao).isdigit() or int(geracao)<1:
            raise ErroReciboGCS("generation do objeto remoto não comprovada")
        # Lê a versão gravada com pré-condição, não uma versão concorrente.
        bytes_lidos=blob.download_as_bytes(
            if_generation_match=int(geracao),timeout=15,
        )
    except Exception as exc:
        if isinstance(exc,ErroReciboGCS):
            raise
        # Nunca vazar bucket, URI, credencial ou corpo nas exceções.
        raise ErroReciboGCS("falha de escrita/leitura GCS ou objeto já existente") from exc
    if not isinstance(bytes_lidos,bytes) or not hmac.compare_digest(dados,bytes_lidos):
        raise ErroReciboGCS("read-back remoto não corresponde ao recibo assinado")
    return {
        **ver,
        "status":"GCS_UPLOAD_CONDICIONAL_READBACK_VERIFICADO",
        "nome_objeto":nome,
        "bucket_id":bucket.name,
        "generation":int(geracao),
        "sha256_bytes":sha256(dados).hexdigest(),
        "upload_condicional":True,
        "readback_mesma_generation":True,
        "retencao_worm_comprovada":False,
        "timestamp_independente_comprovado":False,
        "gcs_ativado_pelo_runtime":True,
        "publicavel":False,
    }


def conferir_recibo_gcs_generation(
    bucket, *, nome_objeto: str, generation: int,
    sha256_esperado: str,
) -> dict:
    """Leitura remota de geração previamente registrada, sem upload."""
    if (not isinstance(nome_objeto,str) or not _OBJ_RE.fullmatch(nome_objeto)
            or type(generation) is not int or generation<1
            or not isinstance(sha256_esperado,str)
            or not re.fullmatch(r"[0-9a-f]{64}",sha256_esperado)
            or bucket is None or not callable(getattr(bucket,"blob",None))):
        raise ErroReciboGCS("localizador GCS ou hash não confiável")
    try:
        blob=bucket.blob(nome_objeto,generation=generation)
        dados=blob.download_as_bytes(
            if_generation_match=generation,timeout=15,
        )
    except Exception as exc:
        raise ErroReciboGCS("recibo remoto não pôde ser recuperado") from exc
    if not isinstance(dados,bytes) or not hmac.compare_digest(
        sha256(dados).hexdigest(),sha256_esperado,
    ):
        raise ErroReciboGCS("objeto remoto adulterado ou divergente")
    return {
        "status":"OBJETO_GCS_GENERATION_E_SHA_VALIDOS",
        "nome_objeto":nome_objeto,"generation":generation,
        "sha256":sha256_esperado,
        "assinatura_mac_conferida":False,
        "retencao_worm_comprovada":False,
        "timestamp_independente_comprovado":False,
        "publicavel":False,
    }
