# Adapted from AgroLogMT/models/maritime_port_state.py (main 2026-10-19); internal use, validate provenance before release.
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable


class MaritimePhysicalState(IntEnum):
    PROGRAMADO = 10
    EM_VIAGEM = 20
    APROXIMACAO = 30
    AREA_PORTUARIA = 40
    FUNDEADO = 50
    AGUARDANDO = 60
    MANOBRA = 70
    ATRACADO = 80
    OPERANDO = 90
    CONCLUIDO = 100
    DESATRACADO = 110
    SAIU = 120


OFFICIAL_EVIDENCE_REQUIRED = frozenset({
    MaritimePhysicalState.OPERANDO,
    MaritimePhysicalState.CONCLUIDO,
})

# These states may be inferred from AIS only when there is a corroborated sequence.
# Explicit operational evidence from a port authority may satisfy the gate without AIS.
AIS_CORROBORATION_REQUIRED = frozenset({
    MaritimePhysicalState.EM_VIAGEM,
    MaritimePhysicalState.APROXIMACAO,
    MaritimePhysicalState.AREA_PORTUARIA,
    MaritimePhysicalState.FUNDEADO,
    MaritimePhysicalState.AGUARDANDO,
    MaritimePhysicalState.MANOBRA,
    MaritimePhysicalState.ATRACADO,
    MaritimePhysicalState.DESATRACADO,
    MaritimePhysicalState.SAIU,
})


@dataclass(frozen=True)
class StateEvidence:
    source_id: str
    evidence_class: str
    observed_at: str
    signal_type: str
    independent_message_count: int = 1
    official_operational: bool = False


def _ascii_token(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return "_".join(text.strip().upper().replace("-", " ").split())


def parse_state(value: str | MaritimePhysicalState) -> MaritimePhysicalState:
    if isinstance(value, MaritimePhysicalState):
        return value
    normalized = _ascii_token(str(value))
    try:
        return MaritimePhysicalState[normalized]
    except KeyError as exc:
        raise ValueError(f"estado fisico maritimo invalido: {value}") from exc


def validate_state_evidence(state: str | MaritimePhysicalState, evidence: Iterable[StateEvidence]) -> None:
    target = parse_state(state)
    rows = list(evidence)
    if not rows:
        raise ValueError("estado fisico exige evidencia")

    has_official = any(row.official_operational for row in rows)
    if target in OFFICIAL_EVIDENCE_REQUIRED and not has_official:
        raise ValueError(f"{target.name} exige evidencia operacional oficial")

    if target in AIS_CORROBORATION_REQUIRED and not has_official:
        ais_rows = [row for row in rows if row.signal_type.strip().upper().startswith("AIS")]
        ais_messages = sum(max(0, int(row.independent_message_count)) for row in ais_rows)
        if ais_messages < 2:
            raise ValueError(
                f"{target.name} exige evidencia operacional oficial ou ao menos duas mensagens AIS independentes"
            )


def validate_transition(previous: str | MaritimePhysicalState, current: str | MaritimePhysicalState) -> None:
    before = parse_state(previous)
    after = parse_state(current)
    if after < before:
        raise ValueError(f"regressao fisica bloqueada: {before.name}->{after.name}")


def canonical_state_order() -> list[str]:
    return [state.name for state in MaritimePhysicalState]
