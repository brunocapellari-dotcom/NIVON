"""Verificação semântica DETERMINÍSTICA de RAW estruturado de anúncio.

Somente JSON de fonte que originalmente publica JSON no contrato V1.
NÃO converter texto, imagem, áudio ou OCR de WhatsApp em JSON e chamar
o JSON resultante de RAW original; nesse caso a prova permanece ausente.
A verificação não autentica o emissor nem cria direito de publicação.
"""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from typing import Mapping
import json
import re

from .quant_core import ErroQuantitativo

CONTRATO = "NIVON_FRETE_JSON_ESTRUTURADO_V1"
IDENTIDADES = (
    "registro_id", "oferta_id", "publicacao_id", "fonte_id",
    "municipio_ibge", "pickup_entity_id", "transportadora_id",
    "destino_ibge", "descarga_entity_id", "produto",
    "equipamento", "regime", "data_referencia", "data_publicacao",
)
VALORES = ("frete_base_brl_t", "pedagio_brl_t", "frete_cheio_brl_t")
CAMPOS = frozenset(("tipo", "contrato", *IDENTIDADES, *VALORES))
VALOR_RE = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,4})?\Z")


def _sem_constante(v: str):
    raise ErroQuantitativo("RAW JSON contém número não finito: " + v)


def _sem_duplicidade(pares):
    out = {}
    for k, v in pares:
        if k in out:
            raise ErroQuantitativo("RAW JSON contém campo duplicado: " + k)
        out[k] = v
    return out


def _valor(v: object, campo: str) -> Decimal | None:
    if v is None:
        return None
    if type(v) is not str or not VALOR_RE.fullmatch(v):
        raise ErroQuantitativo(campo + ": valor monetário não canônico")
    return Decimal(v)


def conferir_semantica_json_estruturado(raw: bytes, registro: Mapping) -> dict:
    """Confere cada campo contra a linha consolidada, sem confiar em claims.

    O RAW é o *objeto JSON estruturado ORIGINAL*, não transcrição posterior.
    A identidade da fonte e o hash deste RAW devem ser verificados em outro
    contrato, antes desta função. Um retorno positivo só prova igualdade
    estrutural do dado fornecido, não que o emissor seja real.
    """
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 2_000_000:
        raise ErroQuantitativo("RAW estruturado deve conter bytes originais válidos")
    if not isinstance(registro, Mapping):
        raise ErroQuantitativo("registro normalizado inválido")
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_sem_duplicidade,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_sem_constante,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ErroQuantitativo("RAW não é JSON UTF-8 estruturado válido") from exc
    if not isinstance(payload, dict) or set(payload) != CAMPOS:
        raise ErroQuantitativo("RAW JSON sem schema exato do anúncio")
    if payload["tipo"] != "FRETE_ANUNCIADO" or payload["contrato"] != CONTRATO:
        raise ErroQuantitativo("RAW não descreve um frete anunciado estruturado V1")
    publicacoes = registro.get("publicacoes_origem")
    if type(publicacoes) is not list or len(publicacoes) != 1:
        raise ErroQuantitativo("RAW exige uma publicação original por registro")
    for campo in IDENTIDADES:
        esperado = publicacoes[0] if campo == "publicacao_id" else registro.get(campo)
        if type(payload[campo]) is not str or payload[campo] != esperado:
            raise ErroQuantitativo(
                "RAW e anúncio normalizado divergem no campo " + campo
            )
    for campo in VALORES:
        a = _valor(payload[campo], campo)
        b = _valor(registro.get(campo), campo)
        if a != b:
            raise ErroQuantitativo(
                "RAW e anúncio normalizado divergem no preço " + campo
            )
    base, pedagio, cheio = (_valor(payload[k], k) for k in VALORES)
    if base is None or base <= 0:
        raise ErroQuantitativo("RAW sem frete base positivo")
    if pedagio is None and cheio is not None:
        raise ErroQuantitativo("RAW cheio sem pedágio explicitamente declarado")
    if pedagio is not None and (cheio is None or cheio != base + pedagio):
        raise ErroQuantitativo("RAW contém frete cheio incoerente")
    return {
        "status": "CORRESPONDENCIA_JSON_ESTRUTURADO_CONFERIDA_OFFLINE",
        "contrato": CONTRATO,
        "campos_comparados": len(IDENTIDADES) + len(VALORES),
        "raw_sha256": sha256(raw).hexdigest(),
        "semantica_whatsapp_livre_verificada": False,
        "autenticidade_externa_comprovada": False,
        "direitos_de_publicacao_comprovados": False,
        "publicavel": False,
    }
