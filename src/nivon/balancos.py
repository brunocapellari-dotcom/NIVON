"""Balanços físicos conservativos: só inputs explicitamente fornecidos, sem dados inventados."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isclose
from typing import Mapping

from .motores import DadoInvalido, numero_positivo

PRODUTOS = frozenset({"SOJA", "MILHO", "FARELO_SOJA", "OLEO_SOJA", "ETANOL", "DDG_DDGS"})
CALENDARIOS = frozenset({"ANO_CIVIL", "SAFRA"})
ESCOPOS = frozenset({"BRASIL", "UF"})
CLASSIFICACOES = frozenset({"OBSERVADO", "INFORMADO", "ESTIMADO", "INFERIDO", "PROJETADO"})


@dataclass(frozen=True)
class Proveniencia:
    fonte_id: str
    classificacao: str
    competencia: str
    referencia: str
    publicacao: str
    coleta: str
    calendario: str

    def __post_init__(self) -> None:
        if self.classificacao not in CLASSIFICACOES:
            raise DadoInvalido("classificacao desconhecida")
        if self.calendario not in CALENDARIOS:
            raise DadoInvalido("calendario nao reconhecido")
        for campo in ("fonte_id", "competencia", "referencia", "publicacao", "coleta"):
            if not str(getattr(self, campo)).strip():
                raise DadoInvalido(f"proveniencia sem {campo}")
        # Não converter datas de publicação/coleta em datas de competência:
        # vintages de previsões precisam preservar todas as datas recebidas.


@dataclass(frozen=True)
class ParcelaConsumo:
    categoria: str
    toneladas: float
    proveniencia: Proveniencia


def decompor_consumo(*, total_t: float, parcelas: tuple[ParcelaConsumo, ...],
                     calendario: str, competencia: str, tolerancia_t: float = 0.001) -> dict:
    """Parcela de ração ou etanol DECOMPÕE o total; não adiciona consumo duas vezes."""
    total = numero_positivo(total_t, "consumo_total_t", aceita_zero=True)
    tolerancia = numero_positivo(tolerancia_t, "tolerancia_t", aceita_zero=True)
    if calendario not in CALENDARIOS or not str(competencia).strip():
        raise DadoInvalido("calendario/competencia ausentes")
    categorias: set[str] = set()
    soma = 0.0
    for item in parcelas:
        if not item.categoria.strip() or item.categoria in categorias:
            raise DadoInvalido("categoria de consumo vazia ou repetida")
        if item.proveniencia.calendario != calendario or item.proveniencia.competencia != competencia:
            raise DadoInvalido("incompatibilidade ano civil/safra ou competencia")
        categorias.add(item.categoria)
        soma += numero_positivo(item.toneladas, item.categoria, aceita_zero=True)
    if soma > total + tolerancia:
        raise DadoInvalido("DUPLA_CONTAGEM_OU_INCONSISTENCIA: parcelas excedem consumo total")
    residual = total - soma
    return {"consumo_total_t": total, "componentes_identificados_t": soma,
            "outros_usos_residuais_t": max(0.0, residual),
            "categorias": sorted(categorias), "calendario": calendario,
            "competencia": competencia,
            "classificacao": "DECOMPOSICAO_SEM_ADICAO_AO_TOTAL"}


@dataclass(frozen=True)
class Balanco:
    produto: str
    escopo: str
    calendario: str
    competencia: str
    estoque_inicial_t: float
    producao_t: float
    importacao_t: float
    entradas_interestaduais_t: float
    consumo_domestico_t: float
    exportacao_t: float
    saidas_interestaduais_t: float
    perdas_t: float
    estoque_final_t: float
    proveniencia: Proveniencia

    def __post_init__(self):
        if self.produto not in PRODUTOS:
            raise DadoInvalido("produto não reconhecido")
        if self.escopo not in ESCOPOS or self.calendario not in CALENDARIOS:
            raise DadoInvalido("escopo ou calendario inválido")
        if not self.competencia.strip():
            raise DadoInvalido("competencia obrigatoria")
        if self.proveniencia.calendario != self.calendario or self.proveniencia.competencia != self.competencia:
            raise DadoInvalido("vintages/períodos incompatíveis")
        for campo in (
            "estoque_inicial_t", "producao_t", "importacao_t", "entradas_interestaduais_t",
            "consumo_domestico_t", "exportacao_t", "saidas_interestaduais_t", "perdas_t",
            "estoque_final_t"
        ):
            numero_positivo(getattr(self, campo), campo, aceita_zero=True)
        if self.escopo == "BRASIL" and (self.entradas_interestaduais_t != 0 or
                                       self.saidas_interestaduais_t != 0):
            raise DadoInvalido("movimentos entre UFs não entram no balanço do Brasil")


def reconciliar_balanco(balanco: Balanco, *, tolerancia_t: float = 0.001) -> dict:
    """Mostra diferença de conservação; nunca reajusta consumo/estoque para forçar fechamento."""
    tolerancia = numero_positivo(tolerancia_t, "tolerancia_t", aceita_zero=True)
    oferta = (balanco.estoque_inicial_t + balanco.producao_t +
              balanco.importacao_t + balanco.entradas_interestaduais_t)
    demanda = (balanco.consumo_domestico_t + balanco.exportacao_t +
               balanco.saidas_interestaduais_t + balanco.perdas_t +
               balanco.estoque_final_t)
    diferenca = oferta - demanda
    conciliado = abs(diferenca) <= tolerancia
    return {"produto": balanco.produto, "escopo": balanco.escopo,
            "calendario": balanco.calendario, "competencia": balanco.competencia,
            "oferta_t": oferta, "destinacao_t": demanda, "diferenca_t": diferenca,
            "conciliado": conciliado, "status": "FECHADO" if conciliado else "DIVERGENTE",
            "classificacao": "CALCULO_COM_ENTRADAS_DECLARADAS",
            "fonte_id": balanco.proveniencia.fonte_id}


def conferir_consistencia_componentes(balanco: Balanco, consumo_decomposto: Mapping[str, object]) -> None:
    """Não permite adicionar 'ração' mais uma vez ao consumo agregado da CONAB."""
    if (balanco.calendario != consumo_decomposto.get("calendario") or
            balanco.competencia != consumo_decomposto.get("competencia")):
        raise DadoInvalido("períodos incompatíveis entre balanço e decomposição")
    if not isclose(balanco.consumo_domestico_t,
                   numero_positivo(consumo_decomposto.get("consumo_total_t"),
                                   "consumo_total_t", aceita_zero=True),
                   abs_tol=0.001, rel_tol=0):
        raise DadoInvalido("consumo agregado difere do total decomposto")
