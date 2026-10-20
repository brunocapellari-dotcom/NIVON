"""Ponte estrita e OFFLINE WhatsApp AI -> anúncios NIVON.

Consume o envelope FreightEvent do WhatsApp AI apenas com uma atestação
EXTERNA de autorização e resolução canônica. O evento, por si só, não
comprova identidade, consentimento, regime, pedágio ou unidade econômica.
Não conecta rede, banco de dados, grupos ou serviço de mensageria.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import hmac
import re
from typing import Mapping
from zoneinfo import ZoneInfo

from .fretes_registros import OfertaFrete, ErroRegistroFrete


class ErroAdaptadorFrete(ErroRegistroFrete):
    pass


_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,179}$")
_MT = ZoneInfo("America/Cuiaba")


def _id(v: object, campo: str) -> str:
    if not isinstance(v, str) or not _ID.fullmatch(v):
        raise ErroAdaptadorFrete(f"{campo}: ID ausente, ambíguo ou não canônico")
    return v


def _dict(v: object, campo: str) -> Mapping:
    if not isinstance(v, Mapping):
        raise ErroAdaptadorFrete(f"{campo}: objeto obrigatório")
    return v


def _decimal(v: object, campo: str, *, zero: bool = False) -> Decimal:
    if isinstance(v, bool) or not isinstance(v, (int, str, Decimal)):
        raise ErroAdaptadorFrete(f"{campo}: decimal textual obrigatório")
    try:
        n = Decimal(str(v))
    except InvalidOperation as exc:
        raise ErroAdaptadorFrete(f"{campo}: decimal inválido") from exc
    if not n.is_finite() or n < 0 or (n == 0 and not zero):
        raise ErroAdaptadorFrete(f"{campo}: preço inválido")
    if len(n.as_tuple().digits) > 18:
        raise ErroAdaptadorFrete(f"{campo}: precisão acima do contrato")
    return n


def _timestamp(v: object, campo: str) -> datetime:
    if isinstance(v, datetime):
        d = v
    elif isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ErroAdaptadorFrete(f"{campo}: timestamp inválido") from exc
    else:
        raise ErroAdaptadorFrete(f"{campo}: timestamp obrigatório")
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroAdaptadorFrete(f"{campo}: timezone obrigatório")
    return d


def _hash(key: bytes, categoria: str, tenant: str, identificador: str) -> str:
    body = ("NIVON_FREIGHT_V1\x00" + categoria + "\x00" + tenant + "\x00" + identificador)
    return hmac.new(key, body.encode("utf-8"), sha256).hexdigest()


def _matching_canonical(entity: object, wanted: str, campo: str) -> None:
    if entity is None:
        return
    e = _dict(entity, campo)
    existing = e.get("canonical_id")
    if existing is not None and existing != wanted:
        raise ErroAdaptadorFrete(f"{campo}: ID externo conflita com resolução verificada")


def _entity_one(event: Mapping, categoria: str) -> object:
    entities = _dict(event.get("entities", {}), "entities")
    values = entities.get(categoria)
    if values is None:
        return None
    if not isinstance(values, list) or len(values) != 1:
        raise ErroAdaptadorFrete(f"{categoria}: exige identidade singular")
    return values[0]


def adaptar_evento_whatsapp(
    evento: Mapping, *, resolucao: Mapping, autorizacao: Mapping,
    data_coleta: datetime, chave_hmac: bytes,
) -> OfertaFrete:
    """Retorna UMA observação anunciada; recusa ambiguidades sem inferir valores.

    Os objetos resolucao/autorizacao só podem vir de camadas confiáveis
    que efetivamente confirmaram evidências, e não de metadata da mensagem.
    Ainda exige homologação E2E com o provedor/autorização antes de uso live.
    """
    evento = _dict(evento, "evento")
    resolucao = _dict(resolucao, "resolucao")
    autorizacao = _dict(autorizacao, "autorizacao")
    if not isinstance(chave_hmac, bytes) or len(chave_hmac) < 32:
        raise ErroAdaptadorFrete("chave HMAC segura fornecida em runtime obrigatória")

    tenant = _id(evento.get("tenant_id"), "tenant_id")
    ev_id = _id(evento.get("event_id"), "event_id")
    versao = evento.get("version")
    if type(versao) is not int or not 1 <= versao <= 1_000_000:
        raise ErroAdaptadorFrete("versão de evento inválida")
    classe = evento.get("classification")
    if classe not in ("FREIGHT_OFFER", "UPDATE"):
        raise ErroAdaptadorFrete("apenas oferta e reajuste comprovado entram na série")
    if classe == "UPDATE":
        if versao <= 1 or not isinstance(evento.get("rate_change"), Mapping):
            raise ErroAdaptadorFrete("reajuste sem versão histórica comprovada")
    if evento.get("truth_classification") != "OBSERVADO":
        raise ErroAdaptadorFrete("classe de observação incorreta")
    unit = evento.get("rate_unit")
    if not isinstance(unit, str) or unit.strip().upper() != "BRL/T":
        raise ErroAdaptadorFrete("unidade não é BRL/t explícito")
    valor = _decimal(evento.get("rate"), "rate")

    origem = _dict(evento.get("origin"), "origin")
    destino = _dict(evento.get("destination"), "destination")
    proveniencia = _dict(evento.get("provenance"), "provenance")
    fonte_provider = _id(proveniencia.get("provider"), "provider")
    source_id = _id(proveniencia.get("source_event_id"), "source_event_id")
    ids = evento.get("source_event_ids")
    if (not isinstance(ids, list) or not ids or len(ids) > 100 or
            any(not isinstance(x, str) or not x for x in ids) or source_id not in ids):
        raise ErroAdaptadorFrete("evento de origem não rastreável")
    pub = _timestamp(evento.get("timestamp"), "timestamp")
    coleta = _timestamp(data_coleta, "data_coleta")
    if pub > coleta:
        raise ErroAdaptadorFrete("publicação no futuro em relação à coleta")

    if (autorizacao.get("status") != "APROVADA"
            or autorizacao.get("tenant_id") != tenant
            or autorizacao.get("provider") != fonte_provider):
        raise ErroAdaptadorFrete("canal/tenant/fonte sem autorização verificada")
    operacoes = autorizacao.get("operacoes_permitidas")
    if (not isinstance(operacoes, (tuple, list, set, frozenset))
            or any(not isinstance(op, str) for op in operacoes)
            or not {"LEITURA", "ARMAZENAMENTO", "ANALISE"}.issubset(set(operacoes))):
        raise ErroAdaptadorFrete("direitos de leitura, armazenamento e análise ausentes")
    fonte = _id(autorizacao.get("fonte_id"), "fonte_id")
    if not _SHA.fullmatch(str(autorizacao.get("comprovante_sha256", ""))):
        raise ErroAdaptadorFrete("prova documental de autorização ausente")

    if (resolucao.get("status") != "VERIFICADA" or
            resolucao.get("tenant_id") != tenant or
            resolucao.get("event_id") != ev_id or
            resolucao.get("version") != versao or
            resolucao.get("source_event_id") != source_id or
            not _SHA.fullmatch(str(resolucao.get("prova_sha256", "")))):
        raise ErroAdaptadorFrete("resolução sem evidência vinculada ao evento/versão")
    municipio = _id(resolucao.get("municipio_ibge"), "municipio_ibge")
    destino_id = _id(resolucao.get("destino_ibge"), "destino_ibge")
    if not (len(municipio) == len(destino_id) == 7
            and municipio.isascii() and municipio.isdecimal()
            and destino_id.isascii() and destino_id.isdecimal()):
        raise ErroAdaptadorFrete("municípios devem usar IDs IBGE de 7 dígitos")
    ponto = _id(resolucao.get("pickup_entity_id"), "pickup_entity_id")
    transp = _id(resolucao.get("transportadora_id"), "transportadora_id")
    descarga = _id(resolucao.get("descarga_entity_id"), "descarga_entity_id")
    _matching_canonical(origem, "mun:" + municipio, "origin")
    _matching_canonical(destino, "mun:" + destino_id, "destination")
    _matching_canonical(_entity_one(evento, "loading_point"), ponto, "loading_point")
    _matching_canonical(_entity_one(evento, "company"), transp, "company")
    produto = _id(resolucao.get("produto"), "produto")
    if evento.get("product") != produto:
        raise ErroAdaptadorFrete("produto divergente da observação")
    equipamento = _id(resolucao.get("equipamento"), "equipamento")
    regime = resolucao.get("regime")
    if regime not in ("PF", "PJ", "NAO_INFORMADO"):
        raise ErroAdaptadorFrete("regime econômico ausente")

    if resolucao.get("rate_role") != "BASE":
        raise ErroAdaptadorFrete("preço anunciado não foi confirmado como base; não inferir frete cheio")
    if _decimal(resolucao.get("frete_base_brl_t"), "frete_base_brl_t") != valor:
        raise ErroAdaptadorFrete("frete base resolvido diverge do evento original")
    pedagio_tipo = resolucao.get("pedagio_tipo")
    if pedagio_tipo == "ADICIONAL_VALOR":
        pedagio = _decimal(resolucao.get("pedagio_brl_t"), "pedagio_brl_t", zero=True)
        cheio = valor + pedagio
    elif pedagio_tipo == "NAO_INFORMADO" and resolucao.get("pedagio_brl_t") is None:
        pedagio = None
        cheio = None
    else:
        raise ErroAdaptadorFrete("condição de pedágio sem comprovação")

    if classe == "UPDATE":
        rc = _dict(evento.get("rate_change"), "rate_change")
        if _decimal(rc.get("current_rate"), "current_rate") != valor:
            raise ErroAdaptadorFrete("rate_change incompatível")
        if _decimal(rc.get("previous_rate"), "previous_rate") == valor:
            raise ErroAdaptadorFrete("reajuste sem alteração efetiva")
        if _timestamp(rc.get("changed_at"), "changed_at") != pub:
            raise ErroAdaptadorFrete("data da revisão divergente do evento")

    return OfertaFrete(
        publicacao_id="wa:" + _hash(chave_hmac, "source", tenant, source_id),
        registro_id="wa:" + _hash(chave_hmac, "record", tenant, f"{ev_id}:{versao}"),
        oferta_id="wa:" + _hash(chave_hmac, "offer", tenant, ev_id),
        municipio_ibge=municipio,
        pickup_entity_id=ponto, transportadora_id=transp,
        destino_ibge=destino_id, descarga_entity_id=descarga,
        produto=produto, equipamento=equipamento, regime=regime,
        frete_base_brl_t=valor, pedagio_brl_t=pedagio,
        frete_cheio_brl_t=cheio,
        data_referencia=pub.astimezone(_MT).date(),
        data_publicacao=pub, data_coleta=coleta, fonte_id=fonte,
    )
