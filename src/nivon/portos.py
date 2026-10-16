"""Contrato inicial dos dez portos, sem declarar que a coleta já foi homologada."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

PORTOS_BR = (
    "RIO_GRANDE", "SAO_FRANCISCO_DO_SUL", "PARANAGUA", "SANTOS",
    "TUBARAO", "ILHEUS", "SALVADOR", "ITAQUI", "BARCARENA_VILA_DO_CONDE", "SANTAREM",
)


@dataclass(frozen=True)
class Programacao:
    porto: str
    navio: str
    duv: str | None
    imo: str | None
    produto: str | None
    toneladas_programadas: float | None
    fonte: str
    coletado_em: str
    status: str = "PROGRAMADO"

    def __post_init__(self):
        if self.porto not in PORTOS_BR:
            raise ValueError("porto fora do cadastro")
        if self.status != "PROGRAMADO":
            raise ValueError("programação não comprova atracação ou realização")
        if not self.navio or not self.fonte or not self.coletado_em:
            raise ValueError("falta identidade ou proveniência")
        if self.toneladas_programadas is not None and self.toneladas_programadas < 0:
            raise ValueError("tonelagem negativa")


def contar_escalas(programacoes: Iterable[Programacao]) -> dict:
    """Contagem de escalas; não somar lotes como se fossem navios distintos."""
    chaves: set[tuple[str, str]] = set()
    sem_id = 0
    for p in programacoes:
        identificador = (p.duv or p.imo or "").strip()
        if not identificador:
            sem_id += 1
            continue
        chaves.add((p.porto, identificador))
    return {"escalas_distintas_identificadas": len(chaves),
            "linhas_sem_identificador_confiavel": sem_id,
            "classificacao": "PROGRAMADO_NAO_REALIZADO"}
