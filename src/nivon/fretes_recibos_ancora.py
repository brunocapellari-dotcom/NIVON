"""Recibo HMAC de cabeça do ledger, emitido fora do arquivo SQLite.

Importante: neste protótipo os instantes e a chave são fornecidos por
runtime local, SEM testemunha de tempo ou storage independente/WORM.
Este recibo verifica consistência, NÃO certifica uma previsão histórica.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Mapping

from .fretes_atestacoes import serializacao_canonica
from .fretes_previsoes_arquivadas import _hora
from .fretes_ledger_persistente import verificar_ledger_frete
from .fretes_ofertas_store import verificar_store_ofertas_frete

VERSAO="NIVON_RECIBO_LEDGER_FRETE_V1"
DOMINIO=b"NIVON_RECIBO_LEDGER_FRETE_V1\x00"
CAMPOS=frozenset({
    "versao","tipo_ledger","emissor_id","sequencia",
    "cabeca_sha256","assinado_em","nonce_hex","mac_sha256",
})


class ErroReciboFrete(ValueError):
    """Falha fechada na integridade de recibo ou local de armazenamento."""


def _hash(h, campo):
    if (not isinstance(h,str) or len(h)!=64
            or any(c not in "0123456789abcdef" for c in h)):
        raise ErroReciboFrete(f"{campo}: SHA256 inválido")
    return h


def _validar_chave(key):
    if not isinstance(key,bytes) or len(key)<32:
        raise ErroReciboFrete("chave de emissão/verificação insuficiente")


def criar_recibo_local_frete(
    *, tipo_ledger: str, emissor_id: str, cabeca_sha256: str,
    sequencia: int, assinado_em: datetime, chave_recibo: bytes,
) -> dict:
    """Assina recibo LOCAL para enviar a cofre externo ainda não integrado."""
    _validar_chave(chave_recibo)
    _hash(cabeca_sha256,"cabeça")
    if tipo_ledger not in ("OFERTAS","PREVISOES"):
        raise ErroReciboFrete("tipo de ledger desconhecido")
    if (not isinstance(emissor_id,str) or not 1<=len(emissor_id)<=120
            or emissor_id.strip()!=emissor_id
            or type(sequencia) is not int or not 1<=sequencia<=1_000_000):
        raise ErroReciboFrete("emissor/sequência inválido")
    if (not isinstance(assinado_em,datetime) or assinado_em.tzinfo is None
            or assinado_em.utcoffset() is None):
        raise ErroReciboFrete("hora do recibo exige timezone")
    corpo={
        "versao":VERSAO,"tipo_ledger":tipo_ledger,
        "emissor_id":emissor_id,"sequencia":sequencia,
        "cabeca_sha256":cabeca_sha256,
        "assinado_em":assinado_em.astimezone(timezone.utc).isoformat(),
        "nonce_hex":secrets.token_hex(16),
    }
    mac=hmac.new(chave_recibo,DOMINIO+serializacao_canonica(corpo),sha256).hexdigest()
    return {**corpo,"mac_sha256":mac}


def verificar_recibo_local_frete(
    recibo: Mapping, *, chave_recibo: bytes, as_of: datetime,
    tipo_esperado: str, emissor_esperado: str,
) -> dict:
    _validar_chave(chave_recibo)
    if not isinstance(recibo,Mapping) or set(recibo)!=CAMPOS:
        raise ErroReciboFrete("esquema de recibo inválido")
    if (recibo["versao"]!=VERSAO or recibo["tipo_ledger"]!=tipo_esperado
            or recibo["emissor_id"]!=emissor_esperado
            or tipo_esperado not in ("OFERTAS","PREVISOES")):
        raise ErroReciboFrete("recibo de outro emissor/domínio")
    _hash(recibo["cabeca_sha256"],"cabeça")
    assinatura=_hash(recibo["mac_sha256"],"mac_sha256")
    if (type(recibo["sequencia"]) is not int
            or not 1<=recibo["sequencia"]<=1_000_000):
        raise ErroReciboFrete("sequência de recibo inválida")
    if recibo["versao"]!=VERSAO or recibo["tipo_ledger"] not in ("OFERTAS","PREVISOES"):
        raise ErroReciboFrete("tipo ou versão de recibo inválido")
    nonce=recibo["nonce_hex"]
    if (not isinstance(nonce,str) or len(nonce)!=32
            or any(x not in "0123456789abcdef" for x in nonce)):
        raise ErroReciboFrete("nonce inválido")
    if not isinstance(as_of,datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ErroReciboFrete("corte temporal obrigatório")
    assinado=_hora(recibo["assinado_em"],"assinado_em")
    if assinado>as_of.astimezone(timezone.utc):
        raise ErroReciboFrete("recibo posterior ao corte")
    payload={k:v for k,v in recibo.items() if k!="mac_sha256"}
    esperado=hmac.new(chave_recibo,DOMINIO+serializacao_canonica(payload),sha256).hexdigest()
    if not hmac.compare_digest(esperado,assinatura):
        raise ErroReciboFrete("recibo MAC inválido")
    return {
        "status":"RECIBO_LOCAL_MAC_CONFERIDO",
        "tipo_ledger":tipo_esperado,
        "sequencia":recibo["sequencia"],
        "cabeca_sha256":recibo["cabeca_sha256"],
        "testemunha_temporal_independente":False,
        "armazenamento_remoto_worm_comprovado":False,
        "publicavel":False,
    }


def auditar_ledger_frete_com_recibo(
    con, recibo: Mapping, *, chave_recibo: bytes, as_of: datetime,
    emissor_recibo: str, chave_previsao: bytes | None = None,
    emissor_previsao: str | None = None,
) -> dict:
    if not isinstance(recibo,Mapping):
        raise ErroReciboFrete("recibo obrigatório")
    tipo=recibo.get("tipo_ledger")
    ok=verificar_recibo_local_frete(
        recibo,chave_recibo=chave_recibo,as_of=as_of,
        tipo_esperado=tipo,emissor_esperado=emissor_recibo,
    )
    try:
        if tipo=="OFERTAS":
            estado=verificar_store_ofertas_frete(
                con,cabeca_esperada_sha256=ok["cabeca_sha256"]
            )
            quantidade=estado["registros"]
        else:
            estado=verificar_ledger_frete(
                con,cabeca_esperada_sha256=ok["cabeca_sha256"],
                chave_verificacao=chave_previsao,
                emissor_esperado=emissor_previsao,
            )
            quantidade=estado["quantidade"]
    except (ValueError,TypeError) as exc:
        raise ErroReciboFrete("ledger diverge do recibo local") from exc
    if quantidade!=ok["sequencia"]:
        raise ErroReciboFrete("quantidade diverge da sequência de recibo")
    if tipo=="PREVISOES" and estado["previsoes"]:
        registrado=_hora(estado["previsoes"][-1]["registrado_em"],"registrado_em")
        if registrado>_hora(recibo["assinado_em"],"assinado_em"):
            raise ErroReciboFrete("recibo anterior à última previsão")
    return {**ok,"status":"RECIBO_E_LEDGER_CONFERIDOS_LOCALMENTE"}


def salvar_recibo_em_diretorio_local(
    recibo: Mapping, *, diretorio_privado: str | Path,
) -> dict:
    """Escrita O_EXCL e fsync, sem sobrescrever. Não substitui WORM/Cloud."""
    if not isinstance(recibo,Mapping) or set(recibo)!=CAMPOS:
        raise ErroReciboFrete("recibo não conforme")
    path=Path(diretorio_privado)
    if (not path.is_absolute() or path.is_symlink() or not path.is_dir()
            or path.stat().st_mode & 0o077):
        raise ErroReciboFrete("diretório de recibos deve existir e ser 0700")
    nonce=recibo["nonce_hex"]
    if (not isinstance(nonce,str) or len(nonce)!=32
            or any(c not in "0123456789abcdef" for c in nonce)):
        raise ErroReciboFrete("nonce de recibo inválido")
    path_final=path / ("frete_"+recibo["tipo_ledger"]+"_"+nonce+".json")
    data=serializacao_canonica(dict(recibo))
    try:
        flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
        fd=os.open(path_final,flags,0o600)
        with os.fdopen(fd,"wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        diretorio_fd=os.open(path,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
        try:
            os.fsync(diretorio_fd)
        finally:
            os.close(diretorio_fd)
    except OSError as exc:
        raise ErroReciboFrete("não foi possível persistir recibo local") from exc
    return {
        "status":"RECIBO_LOCAL_GRAVADO_SEM_ANCORA_EXTERNA",
        "caminho_local":str(path_final),
        "sha256":sha256(data).hexdigest(),
        "armazenamento_independente_comprovado":False,
        "timestamp_qualificado_comprovado":False,
        "publicavel":False,
    }
