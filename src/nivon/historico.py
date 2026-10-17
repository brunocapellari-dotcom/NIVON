"""Histórico bitemporal e consultas as-of: evita olhar revisões publicadas no futuro."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Iterable

ESTADOS = frozenset({"OBSERVADO", "ESTIMADO", "PROJETADO", "INFORMADO", "INFERIDO"})


class ErroHistorico(ValueError):
    pass


@dataclass(frozen=True)
class Observacao:
    fonte: str
    variavel: str
    produto: str
    regiao: str
    unidade: str
    competencia: str
    calendario: str
    referencia: date
    publicacao: date
    coleta: datetime
    valor: float
    natureza: str = "OBSERVADO"
    edicao: str = ""

    def __post_init__(self):
        for atributo in ("fonte", "variavel", "produto", "regiao", "unidade",
                         "competencia", "calendario"):
            if not isinstance(getattr(self, atributo), str) or not getattr(self, atributo).strip():
                raise ErroHistorico(f"{atributo} obrigatório")
        if not isinstance(self.referencia, date) or not isinstance(self.publicacao, date):
            raise ErroHistorico("referencia/publicacao precisam ser datas")
        if not isinstance(self.coleta, datetime) or self.coleta.tzinfo is None:
            raise ErroHistorico("coleta precisa ter timezone")
        if self.natureza not in ESTADOS:
            raise ErroHistorico("natureza de evidência desconhecida")
        if isinstance(self.valor, bool) or not isinstance(self.valor, (float, int)) or not isfinite(self.valor):
            raise ErroHistorico("valor nulo ou não finito")
        if self.coleta.astimezone(timezone.utc).date() < self.publicacao:
            raise ErroHistorico("coleta não pode anteceder a data da publicação")
        if self.calendario not in ("ANO_CIVIL", "SAFRA", "MENSAL"):
            raise ErroHistorico("calendario inválido")

    @property
    def chave(self) -> tuple[str, ...]:
        # A fonte faz parte da chave; fontes distintas não se substituem silenciosamente.
        return (self.fonte, self.variavel, self.produto, self.regiao, self.unidade,
                self.calendario, self.competencia)


def visao_na_data(
    observacoes: Iterable[Observacao], *,
    data_corte_publicacao: date,
    instante_corte_coleta: datetime,
) -> list[Observacao]:
    """Escolhe a última versão CONHECIDA na época, sem look-ahead bias.

    Conflitos distintos na mesma data/instante são rejeitados, não resolvidos
    arbitrariamente pela ordem de entrada.
    """
    if instante_corte_coleta.tzinfo is None:
        raise ErroHistorico("corte de coleta exige timezone")
    selecionadas: dict[tuple[str, ...], Observacao] = {}
    for o in observacoes:
        if o.publicacao > data_corte_publicacao or o.coleta > instante_corte_coleta:
            continue
        anterior = selecionadas.get(o.chave)
        if anterior is None or (o.publicacao, o.coleta) > (anterior.publicacao, anterior.coleta):
            selecionadas[o.chave] = o
        elif (o.publicacao, o.coleta) == (anterior.publicacao, anterior.coleta) and (
            o.valor != anterior.valor or o.natureza != anterior.natureza or o.edicao != anterior.edicao
        ):
            raise ErroHistorico("edições conflitantes com mesma chave e carimbos temporais")
    return [selecionadas[k] for k in sorted(selecionadas)]


def serie_anual(
    observacoes: Iterable[Observacao], *, variavel: str, produto: str,
    regiao: str, fonte: str, unidade: str,
) -> dict[int, float]:
    """Apenas série anual observada e já selecionada as-of; sem misturar calendários."""
    filtradas = [o for o in observacoes if o.variavel == variavel and
                 o.produto == produto and o.regiao == regiao and o.fonte == fonte and
                 o.unidade == unidade]
    if not filtradas:
        raise ErroHistorico("nenhuma observação da série")
    if any(o.calendario != "ANO_CIVIL" or o.natureza != "OBSERVADO" or
           not o.competencia.isdecimal() or len(o.competencia) != 4 for o in filtradas):
        raise ErroHistorico("série anual exige ano civil e observações, não projeções")
    serie: dict[int, float] = {}
    for o in filtradas:
        ano = int(o.competencia)
        if ano in serie:
            raise ErroHistorico("ano duplicado; selecione primeiro a visão as-of")
        serie[ano] = float(o.valor)
    return dict(sorted(serie.items()))
