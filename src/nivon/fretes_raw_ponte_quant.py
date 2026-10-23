"""Ponte offline de RAW original -> anúncio consolidado -> série Quant.

Uma assinatura HMAC de um coletor confiável liga bytes RAW a metadados de
captura de CADA anúncio. Não é prova da legitimidade/verdade do anunciante,
nem de licença, nem de recibo WORM externo ou capacidade preditiva.
Dados sem recibos válidos falham fechados. Não aceita digest de painel R01.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
from typing import Mapping, Sequence

from .fretes_atestacoes import serializacao_canonica
from .integracao_frete_quant import preparar_serie_frete_anunciado
from .quant_core import ErroQuantitativo, _instante

DOMINIO = b"NIVON_RAW_FRETE_V1\x00"
CAMPOS = frozenset({
    "versao", "emissor_id", "registro_id", "oferta_id", "publicacao_id",
    "fonte_id", "raw_sha256", "publicado_em", "capturado_em", "emitido_em",
    "assinatura_hmac_sha256",
})


def _texto(v: object, campo: str) -> str:
    if not isinstance(v, str) or not v or v.strip() != v or len(v) > 180:
        raise ErroQuantitativo(f"{campo}: identificação inválida")
    return v


def _recibo(
    row: Mapping, *, raw: bytes, recibo: Mapping,
    chave_captura: bytes, emissor: str, corte: datetime,
) -> dict:
    if not isinstance(row, Mapping) or not isinstance(recibo, Mapping):
        raise ErroQuantitativo("registro ou recibo RAW inválido")
    if set(recibo) != CAMPOS or type(recibo["versao"]) is not int or recibo["versao"] != 1:
        raise ErroQuantitativo("recibo RAW incompleto ou versão inválida")
    if recibo["emissor_id"] != emissor:
        raise ErroQuantitativo("emissor RAW não reconhecido")
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 2_000_000:
        raise ErroQuantitativo("bytes originais RAW obrigatórios e limitados")
    pub_ids = row.get("publicacoes_origem")
    if not isinstance(pub_ids, list) or len(pub_ids) != 1:
        raise ErroQuantitativo(
            "RAW de republicações exige evidência por origem; não escolher arbitrariamente"
        )
    for k in ("registro_id", "oferta_id", "fonte_id"):
        if recibo[k] != row.get(k):
            raise ErroQuantitativo(f"recibo RAW não corresponde ao {k}")
        _texto(recibo[k], k)
    if recibo["publicacao_id"] != pub_ids[0]:
        raise ErroQuantitativo("recibo RAW com publicação diferente")
    _texto(recibo["publicacao_id"], "publicacao_id")
    digest = sha256(raw).hexdigest()
    if recibo["raw_sha256"] != digest:
        raise ErroQuantitativo("SHA do RAW não corresponde aos bytes capturados")
    if recibo["publicado_em"] != row.get("data_publicacao"):
        raise ErroQuantitativo("recibo RAW altera o timestamp publicado")
    pub = _instante(recibo["publicado_em"], "publicado_em")
    capturado = _instante(recibo["capturado_em"], "capturado_em")
    emitido = _instante(recibo["emitido_em"], "emitido_em")
    recebido = _instante(row.get("data_coleta"), "data_coleta")
    if not pub <= capturado <= emitido <= recebido <= corte:
        raise ErroQuantitativo("recibo RAW não estava disponível no as-of registrado")
    sig = recibo["assinatura_hmac_sha256"]
    if not isinstance(sig, str) or len(sig) != 64 or any(c not in "0123456789abcdef" for c in sig):
        raise ErroQuantitativo("assinatura RAW inválida")
    assinado = {k: v for k, v in recibo.items() if k != "assinatura_hmac_sha256"}
    try:
        esperado = hmac.new(
            chave_captura, DOMINIO + serializacao_canonica(assinado), sha256
        ).hexdigest()
    except (TypeError, ValueError) as exc:
        raise ErroQuantitativo("recibo RAW não serializável") from exc
    if not hmac.compare_digest(esperado, sig):
        raise ErroQuantitativo("recibo RAW não autenticado pela chave do coletor")
    existente = row.get("edicao_sha256")
    if existente is not None and existente != digest:
        raise ErroQuantitativo("digest pré-existente difere do RAW autenticado")
    return {**row, "edicao_sha256": digest}


def preparar_fretes_quant_com_raw(
    registros: Sequence[Mapping], *, raws: Mapping[str, bytes],
    recibos: Mapping[str, Mapping], chave_captura: bytes,
    emissor_esperado: str, chave_economica: Mapping, fonte_id: str,
    tipo_valor: str, as_of: str,
) -> dict:
    """Requer TODAS as edições RAW com recibos verificados pelo chamador.

    Chave de captura vem do runtime confiável, nunca do evento nem do recibo.
    Um resultado positivo atesta apenas integridade local e vínculo HMAC
    declarados por este emissor. A prova independente do provedor, licença,
    recibo externo durável e direito de publicar seguem pendentes.
    """
    if (not isinstance(chave_captura, bytes) or len(chave_captura) < 32
            or not isinstance(emissor_esperado, str)
            or not emissor_esperado or len(emissor_esperado) > 180):
        raise ErroQuantitativo("chave independente e emissor RAW obrigatórios")
    if not isinstance(registros, (list, tuple)) or not 1 <= len(registros) <= 10000:
        raise ErroQuantitativo("lote de RAW fora dos limites")
    if not isinstance(raws, Mapping) or not isinstance(recibos, Mapping):
        raise ErroQuantitativo("arquivos/recibos RAW ausentes")
    corte = _instante(as_of, "as_of")
    ids = [_texto(r.get("registro_id"), "registro_id") if isinstance(r, Mapping)
           else _texto(None, "registro_id") for r in registros]
    if len(set(ids)) != len(ids) or set(ids) != set(raws) or set(ids) != set(recibos):
        raise ErroQuantitativo("cobertura RAW parcial, duplicada ou com IDs extras")
    validados = [
        _recibo(row, raw=raws[row["registro_id"]],
                recibo=recibos[row["registro_id"]],
                chave_captura=chave_captura, emissor=emissor_esperado,
                corte=corte)
        for row in registros
    ]
    serie = preparar_serie_frete_anunciado(
        validados, chave=chave_economica, fonte_id=fonte_id,
        tipo_valor=tipo_valor, as_of=as_of,
    )
    # A ponte NÃO modifica gates de operacionalidade do contrato quantitativo.
    if serie["status"] != "SERIE_ECONOMICA_INDIVIDUAL_PARA_TESTES_OFFLINE":
        raise ErroQuantitativo("série com RAW autenticado não passou contrato Quant")
    return {
        **serie,
        "recibos_raw_conferidos": len(validados),
        "raw_digest_sha256": sorted(x["edicao_sha256"] for x in validados),
        "integridade_hmac_coletor_verificada": True,
        "autenticidade_origem_independente_comprovada": False,
        "armazenamento_worm_comprovado": False,
        "direitos_redistribuicao_comprovados": False,
        "asof_pronto": False,
        "uso_preditivo_real_autorizado": False,
        "publicavel": False,
        "alerta_raw": "Recibo HMAC de coletor não substitui prova externa da publicação original, licença, imutabilidade histórica ou calibração.",
    }
