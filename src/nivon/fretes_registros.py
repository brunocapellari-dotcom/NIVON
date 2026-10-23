"""Registro offline de FRETES ANUNCIADOS por estabelecimento e transportadora.

Não produz média municipal, não infere frete contratado nem tonelagem realizada.
Deduplicação exige oferta_id resolvida com evidência, não similaridade de nomes.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Iterable


class ErroRegistroFrete(ValueError):
    pass


def _identidade(v: str, campo: str) -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > 180:
        raise ErroRegistroFrete(f"{campo}: identificador canônico obrigatório")
    return v.strip()


def _ibge(v: str) -> str:
    if not isinstance(v, str) or len(v) != 7 or not v.isascii() or not v.isdecimal():
        raise ErroRegistroFrete("município deve usar código IBGE de 7 dígitos")
    return v


def _reais(v: Decimal | None, campo: str) -> Decimal | None:
    if v is None:
        return None
    if not isinstance(v, Decimal) or not v.is_finite() or v < 0:
        raise ErroRegistroFrete(f"{campo}: Decimal finito não negativo obrigatório")
    return v


@dataclass(frozen=True)
class OfertaFrete:
    publicacao_id: str
    registro_id: str
    oferta_id: str
    municipio_ibge: str
    pickup_entity_id: str
    transportadora_id: str
    destino_ibge: str
    descarga_entity_id: str
    produto: str
    equipamento: str
    regime: str
    frete_base_brl_t: Decimal
    pedagio_brl_t: Decimal | None
    frete_cheio_brl_t: Decimal | None
    data_referencia: date
    data_publicacao: datetime
    data_coleta: datetime
    fonte_id: str
    provedor_id: str = ""  # Escopo original atestado; vazio somente em legados sem provedor

    def __post_init__(self) -> None:
        for campo in ("publicacao_id", "registro_id", "oferta_id",
                      "pickup_entity_id", "transportadora_id",
                      "descarga_entity_id", "produto", "equipamento", "fonte_id"):
            _identidade(getattr(self, campo), campo)
        if self.provedor_id:
            _identidade(self.provedor_id, "provedor_id")
        _ibge(self.municipio_ibge)
        _ibge(self.destino_ibge)
        if self.regime not in {"PF", "PJ", "NAO_INFORMADO"}:
            raise ErroRegistroFrete("regime PF/PJ inválido")
        base = _reais(self.frete_base_brl_t, "frete_base")
        pedagio = _reais(self.pedagio_brl_t, "pedagio")
        cheio = _reais(self.frete_cheio_brl_t, "frete_cheio")
        if base is None or base <= 0:
            raise ErroRegistroFrete("frete base anunciado deve ser positivo")
        if pedagio is not None and cheio is not None and cheio != base + pedagio:
            raise ErroRegistroFrete("frete cheio deve ser igual a base + pedágio informado")
        if cheio is not None and cheio < base:
            raise ErroRegistroFrete("frete cheio não pode ser inferior ao base")
        if not isinstance(self.data_referencia, date) or isinstance(self.data_referencia, datetime):
            raise ErroRegistroFrete("data de referência inválida")
        if not all(isinstance(v, datetime) and v.tzinfo is not None
                   and v.utcoffset() is not None
                   for v in (self.data_publicacao, self.data_coleta)):
            raise ErroRegistroFrete("publicação/coleta exigem timezone")
        if self.data_publicacao > self.data_coleta:
            raise ErroRegistroFrete("publicação não pode ser posterior à coleta")
        if self.data_referencia > self.data_publicacao.astimezone(ZoneInfo("America/Cuiaba")).date():
            raise ErroRegistroFrete("referência futura à publicação")

    def identidade_economica(self) -> tuple:
        return (self.municipio_ibge, self.pickup_entity_id,
                self.transportadora_id, self.destino_ibge,
                self.descarga_entity_id, self.produto,
                self.equipamento, self.regime)

    def assinatura_republicacao(self) -> tuple:
        return (self.fonte_id, self.provedor_id, self.oferta_id, self.data_referencia,
                self.identidade_economica(), self.frete_base_brl_t,
                self.pedagio_brl_t, self.frete_cheio_brl_t)


def consolidar_ofertas(ofertas: Iterable[OfertaFrete]) -> dict:
    """Deduplica reenvios comprovados e fornece SOMENTE contagens por município.

    Mantém todo preço por transportadora/estabelecimento, sem estatística
    municipal de preços. Mudança efetiva de preço é novo registro comercial.
    """
    rows = list(ofertas)
    if len(rows) > 100_000:
        raise ErroRegistroFrete("lote de ingestão acima do limite")
    distinct: dict[tuple, OfertaFrete] = {}
    ids_oferta: dict[tuple[str, date], tuple] = {}
    registro_ids: dict[str, tuple] = {}
    referencias: dict[tuple, set[str]] = defaultdict(set)
    for item in rows:
        if not isinstance(item, OfertaFrete):
            raise ErroRegistroFrete("registro fora do contrato OfertaFrete")
        assinatura = item.assinatura_republicacao()
        id_key = (item.fonte_id, item.provedor_id, item.oferta_id, item.data_referencia)
        identidade = item.identidade_economica()
        if id_key in ids_oferta and ids_oferta[id_key] != identidade:
            raise ErroRegistroFrete("oferta_id reutilizada para identidades incompatíveis")
        ids_oferta[id_key] = identidade
        if item.registro_id in registro_ids and registro_ids[item.registro_id] != assinatura:
            raise ErroRegistroFrete("registro_id contém eventos comerciais conflitantes")
        registro_ids[item.registro_id] = assinatura
        referencias[assinatura].add(item.publicacao_id)
        # Escolher representante de forma determinística independentemente
        # da ordem dos eventos. A primeira publicação verificável prevalece.
        if (assinatura not in distinct or
                (item.data_publicacao, item.data_coleta, item.publicacao_id,
                 item.registro_id) <
                (distinct[assinatura].data_publicacao,
                 distinct[assinatura].data_coleta,
                 distinct[assinatura].publicacao_id,
                 distinct[assinatura].registro_id)):
            distinct[assinatura] = item

    estabelecimentos: dict[str, set[str]] = defaultdict(set)
    estabelecimentos_destino: dict[tuple[str, str], set[str]] = defaultdict(set)
    por_ponto: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for x in distinct.values():
        estabelecimentos[x.municipio_ibge].add(x.pickup_entity_id)
        estabelecimentos_destino[(x.municipio_ibge, x.destino_ibge)].add(x.pickup_entity_id)
        por_ponto[(x.municipio_ibge, x.pickup_entity_id, x.destino_ibge)].add(x.transportadora_id)

    registros = []
    for assinatura, x in sorted(distinct.items(), key=lambda kv:
                                (kv[1].data_referencia, kv[1].registro_id)):
        registros.append({
            "registro_id": x.registro_id,
            "oferta_id": x.oferta_id,
            "municipio_ibge": x.municipio_ibge,
            "pickup_entity_id": x.pickup_entity_id,
            "transportadora_id": x.transportadora_id,
            "destino_ibge": x.destino_ibge,
            "descarga_entity_id": x.descarga_entity_id,
            "produto": x.produto, "equipamento": x.equipamento,
            "regime": x.regime,
            "frete_base_brl_t": str(x.frete_base_brl_t),
            "pedagio_brl_t": str(x.pedagio_brl_t) if x.pedagio_brl_t is not None else None,
            "frete_cheio_brl_t": str(x.frete_cheio_brl_t) if x.frete_cheio_brl_t is not None else None,
            "data_referencia": x.data_referencia.isoformat(),
            "data_publicacao": x.data_publicacao.isoformat(),
            "data_coleta": x.data_coleta.isoformat(),
            "fonte_id": x.fonte_id,
            "provedor_id": x.provedor_id or None,
            "publicacoes_origem": sorted(referencias[assinatura]),
            "natureza": "FRETE_ANUNCIADO_NAO_CONTRATADO",
        })
    return {
        "natureza": "FRETE_ANUNCIADO_NAO_CONTRATADO",
        "total_publicacoes_recebidas": len({x.publicacao_id for x in rows}),
        "total_registros_divulgados": len(rows),
        "total_registros_individuais_deduplicados": len(registros),
        "republicacoes_confirmadas": len(rows) - len(registros),
        "municipios": len(estabelecimentos),
        "destinos": len({x.destino_ibge for x in distinct.values()}),
        "transportadoras": len({x.transportadora_id for x in distinct.values()}),
        "pontos_unicos_por_municipio": [
            {"municipio_ibge": mun, "quantidade": len(pontos),
             "pickup_entity_ids": sorted(pontos)}
            for mun, pontos in sorted(estabelecimentos.items())
        ],
        "pontos_unicos_por_municipio_destino": [
            {"municipio_ibge": mun, "destino_ibge": dest,
             "quantidade": len(pontos), "pickup_entity_ids": sorted(pontos)}
            for (mun, dest), pontos in sorted(estabelecimentos_destino.items())
        ],
        "pontos_com_multiplas_transportadoras": [
            {"municipio_ibge": mun, "pickup_entity_id": ponto,
             "destino_ibge": dest, "transportadoras": sorted(carriers)}
            for (mun, ponto, dest), carriers in sorted(por_ponto.items()) if len(carriers) > 1
        ],
        "registros": registros,
    }


def distancia_e_custo(*, frete_cheio_brl_t: Decimal, distancia_km: Decimal,
                      distancia_verificada: bool,
                      carga_efetiva_t: Decimal | None = None) -> dict:
    """R$/TKU = (R$/t)/km; R$/km por veículo exige carga efetiva.

    Métrica derivada NÃO equivale ao custo real do transportador nem
    à distância percorrida por viagem observada.
    """
    valor = _reais(frete_cheio_brl_t, "frete_cheio_brl_t")
    km = _reais(distancia_km, "distancia_km")
    if not distancia_verificada or km is None or km <= 0 or valor is None:
        raise ErroRegistroFrete("valor e distância de rota verificada obrigatórios")
    saida = {"frete_brl_t": str(valor), "distancia_rodoviaria_km": str(km),
             "frete_brl_tku_estimado": str(valor / km),
             "classe": "DERIVADO_DE_ANUNCIO_E_DISTANCIA_NAO_CUSTO_REAL"}
    if carga_efetiva_t is not None:
        toneladas = _reais(carga_efetiva_t, "carga_efetiva_t")
        if toneladas is None or toneladas <= 0:
            raise ErroRegistroFrete("carga efetiva deve ser positiva")
        saida["receita_hipotetica_brl_km_por_veiculo"] = str(valor * toneladas / km)
    return saida
