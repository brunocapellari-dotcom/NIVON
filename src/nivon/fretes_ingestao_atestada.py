"""Ingestão ATÔMICA e idempotente de eventos WhatsApp AI previamente atestados.

Sem conectividade com WhatsApp, banco remoto ou cloud. Operador fornece
raw_bytes (não persistidos), chaves de diferentes atestadores, coletado_em e
relógio confiável do processo; este último NÃO é um carimbo de tempo externo.
O contrato só aceita raw_sha256 assinado pelo resolvedor independente e
vinculado ao hash do evento transformado.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
from typing import Mapping, Sequence
import sqlite3

from .fretes_adapter_whatsapp import adaptar_evento_whatsapp, ErroAdaptadorFrete
from .fretes_atestacoes import hash_evento
from .fretes_ofertas_store import (
    GENESIS, ErroStoreOfertaFrete, anexar_lote_ofertas_frete,
    verificar_store_ofertas_frete, _object,
)

CAMPOS_ENVELOPE=frozenset({
    "evento","resolucao","autorizacao","data_coleta","raw_bytes",
})
MAX_RAW_BYTES=200_000
MAX_ATRASO_SEGUNDOS=300


class ErroIngestaoFrete(ErroStoreOfertaFrete):
    """Admissão conservadora de anúncios previamente autorizados."""


def _instante(value: object, field: str) -> datetime:
    if (not isinstance(value,datetime) or value.tzinfo is None
            or value.utcoffset() is None):
        raise ErroIngestaoFrete(f"{field}: instante com timezone obrigatório")
    return value.astimezone(timezone.utc)


def _sha(v: object, name: str) -> str:
    if (not isinstance(v,str) or len(v)!=64
            or any(c not in "0123456789abcdef" for c in v)):
        raise ErroIngestaoFrete(f"{name}: SHA-256 hexadecimal obrigatório")
    return v


def ingerir_lote_whatsapp_atestado(
    con: sqlite3.Connection, envelopes: Sequence[Mapping], *,
    cabeca_anterior_sha256: str, recebido_em: datetime,
    chave_pseudonimizacao: bytes, chaves_atestacao: Mapping,
    emissores_atestacao: Mapping,
) -> dict:
    """Valida TODOS os envelopes ANTES de persistir; rejeita conflitos.

    Retentativa byte-a-byte de mesmo anúncio assinado é idempotente. Não
    reinterpreta coleta tardia como anúncio novo. Uma inconsistência invalida
    todo o lote; nunca faz merge fuzzy de empresas ou pontos de embarque.
    """
    if (not isinstance(envelopes,(list,tuple)) or not 1<=len(envelopes)<=500
            or any(not isinstance(x,Mapping) or set(x)!=CAMPOS_ENVELOPE
                   for x in envelopes)):
        raise ErroIngestaoFrete("envelopes ausentes ou estrutura de lote incompatível")
    if (not isinstance(con,sqlite3.Connection)
            or not isinstance(chave_pseudonimizacao,bytes)
            or len(chave_pseudonimizacao)<32
            or not isinstance(chaves_atestacao,Mapping)
            or not isinstance(emissores_atestacao,Mapping)):
        raise ErroIngestaoFrete("ambiente de verificação de origem não configurado")
    instante=_instante(recebido_em,"recebido_em")
    _sha(cabeca_anterior_sha256,"cabeca_anterior_sha256")
    if con.in_transaction:
        raise ErroIngestaoFrete("transação SQLite pendente")
    # Cabeça recebida de cofre externo pelo chamador; não usar o próprio DB.
    try:
        anterior=verificar_store_ofertas_frete(
            con,cabeca_esperada_sha256=cabeca_anterior_sha256,
        )
    except ErroStoreOfertaFrete as exc:
        raise ErroIngestaoFrete("cabeça anterior não confere com o store") from exc
    existentes={
        r.registro_id:(_object(r),e)
        for r,e in zip(anterior["ofertas"],anterior["evidencias_declaradas"])
    }
    novos={}
    recebidos=0
    repetidos=0
    for item in envelopes:
        ev=item["evento"]
        direitos=item["autorizacao"]
        resolucao=item["resolucao"]
        coleta=_instante(item["data_coleta"],"data_coleta")
        raw=item["raw_bytes"]
        if (not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_RAW_BYTES
                or not isinstance(ev,Mapping)
                or not isinstance(resolucao,Mapping)
                or not isinstance(direitos,Mapping)):
            raise ErroIngestaoFrete("RAW, evento ou atestação ausente/inválida")
        if not coleta<=instante<=coleta+timedelta(seconds=MAX_ATRASO_SEGUNDOS):
            raise ErroIngestaoFrete("recebimento retroativo ou fora da janela online")
        raw_sha=sha256(raw).hexdigest()
        if not hmac.compare_digest(
            _sha(resolucao.get("raw_sha256"),"resolucao.raw_sha256"),raw_sha
        ):
            raise ErroIngestaoFrete("hash do RAW diferente do atestado pelo resolvedor")
        # O adapter exige HMAC de DOIS emissores diferentes, sobre os hashes
        # e o conteúdo da resolução/autorização, direitos e versão do evento.
        try:
            registro=adaptar_evento_whatsapp(
                ev,resolucao=resolucao,autorizacao=direitos,
                data_coleta=coleta,chave_hmac=chave_pseudonimizacao,
                chaves_atestacao=chaves_atestacao,
                emissores_atestacao=emissores_atestacao,
            )
        except ErroAdaptadorFrete as exc:
            raise ErroIngestaoFrete("evento recusado na validação externa") from exc
        tenant=ev.get("tenant_id")
        fonte=ev.get("provenance",{}).get("provider")
        if not isinstance(tenant,str) or not isinstance(fonte,str):
            raise ErroIngestaoFrete("tenant/provedor não identificado")
        tenant_hash=hmac.new(
            chave_pseudonimizacao,
            b"NIVON_TENANT_FRETE_V1\x00"+tenant.encode("utf-8"),
            sha256,
        ).hexdigest()
        prova={
            "raw_sha256":raw_sha,
            "direitos_sha256":hash_evento(direitos),
            "resolucao_sha256":hash_evento(resolucao),
            "provedor":fonte,
            "tenant_pseudonimizado":tenant_hash,
        }
        key=registro.registro_id
        obj=_object(registro)
        if key in existentes:
            if (obj,prova)!=existentes[key]:
                raise ErroIngestaoFrete("mesmo registro_id com prova/valor divergente")
            repetidos+=1
        elif key in novos:
            old=novos[key]
            if (obj,prova)!=(old[0],old[1]):
                raise ErroIngestaoFrete("evento duplicado com edição conflitante no lote")
            repetidos+=1
        else:
            novos[key]=(obj,prova,registro)
        recebidos+=1
    if not novos:
        return {
            "status":"INGESTAO_IDEMPOTENTE_SEM_NOVOS_REGISTROS",
            "publicacoes_recebidas":recebidos,
            "registros_individuais_inseridos":0,
            "republicacoes_idempotentes":repetidos,
            "cabeca_sha256":cabeca_anterior_sha256,
            "total_store":anterior["registros"],
            "origem_externa_autenticada_operacionalmente":False,
            "publicavel":False,
        }
    registros=[a[2] for a in novos.values()]
    evidencias={a[2].registro_id:a[1] for a in novos.values()}
    gravado=anexar_lote_ofertas_frete(
        con,registros,evidencias=evidencias,
        cabeca_anterior_sha256=cabeca_anterior_sha256,
    )
    return {
        "status":"INGESTAO_ATTESTADA_OFFLINE_PENDENTE_HOMOLOGACAO",
        "publicacoes_recebidas":recebidos,
        "registros_individuais_inseridos":gravado["adicionados"],
        "republicacoes_idempotentes":repetidos,
        "cabeca_sha256":gravado["cabeca_sha256"],
        "total_store":gravado["total"],
        "integridade_raw_sha256_vinculada":True,
        "assinaturas_declaradas_verificadas":True,
        "origem_externa_autenticada_operacionalmente":False,
        "ancora_temporal_independente_comprovada":False,
        "publicavel":False,
    }
