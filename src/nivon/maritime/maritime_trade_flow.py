# Adapted from AgroLogMT/models/maritime_trade_flow.py (main 2026-10-19); review provenance before external release.
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class PortTradeAggregate:
    port_id: str
    period: str
    product: str
    observed_mass_t: float
    source_id: str
    evidence_class: str = "OBSERVADO"


@dataclass(frozen=True)
class LineupAggregate:
    port_id: str
    period: str
    product: str
    programmed_mass_t: float
    vessel_calls: int
    source_id: str
    evidence_class: str = "INFORMADO"


@dataclass(frozen=True)
class TradeFlowSignal:
    port_id: str
    period: str
    product: str
    observed_trade_mass_t: float | None
    programmed_lineup_mass_t: float | None
    programmed_calls: int | None
    programmed_to_observed_ratio: float | None
    status: str
    evidence_class: str
    flags: tuple[str, ...]
    vessel_level_attribution_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _key(port_id: str, period: str, product: str) -> tuple[str, str, str]:
    return (str(port_id).strip().upper(), str(period).strip(), str(product).strip().upper())


def build_trade_flow_signals(
    observed: Iterable[PortTradeAggregate],
    programmed: Iterable[LineupAggregate],
) -> list[TradeFlowSignal]:
    """Join port/product/period aggregates without attributing customs totals to ships.

    Comex/ANTAQ aggregates and line-up programming may be compared at a compatible
    aggregate grain only. This function explicitly forbids deriving buyer, trading
    company, contracted tonnage or customs mass for an individual vessel.
    """
    observed_map: dict[tuple[str, str, str], float] = {}
    programmed_map: dict[tuple[str, str, str], tuple[float, int]] = {}

    for row in observed:
        if row.observed_mass_t < 0:
            raise ValueError("observed_mass_t não pode ser negativa")
        key = _key(row.port_id, row.period, row.product)
        observed_map[key] = observed_map.get(key, 0.0) + float(row.observed_mass_t)

    for row in programmed:
        if row.programmed_mass_t < 0 or row.vessel_calls < 0:
            raise ValueError("programação não pode ter valores negativos")
        key = _key(row.port_id, row.period, row.product)
        mass, calls = programmed_map.get(key, (0.0, 0))
        programmed_map[key] = (mass + float(row.programmed_mass_t), calls + int(row.vessel_calls))

    out: list[TradeFlowSignal] = []
    for key in sorted(set(observed_map) | set(programmed_map)):
        port_id, period, product = key
        observed_mass = observed_map.get(key)
        programmed_values = programmed_map.get(key)
        programmed_mass = programmed_values[0] if programmed_values else None
        calls = programmed_values[1] if programmed_values else None
        flags: list[str] = ["aggregate_only_no_vessel_customs_attribution"]

        ratio = None
        if observed_mass is not None and observed_mass > 0 and programmed_mass is not None:
            ratio = programmed_mass / observed_mass
        if observed_mass is None:
            flags.append("observed_trade_missing")
        if programmed_mass is None:
            flags.append("lineup_programming_missing")

        if observed_mass is not None and programmed_mass is not None:
            status = "AGGREGATE_CONFRONTED"
            evidence_class = "INFERIDO"
        elif observed_mass is not None:
            status = "OBSERVED_ONLY"
            evidence_class = "OBSERVADO"
        else:
            status = "PROGRAMMED_ONLY"
            evidence_class = "INFORMADO"

        out.append(TradeFlowSignal(
            port_id=port_id,
            period=period,
            product=product,
            observed_trade_mass_t=observed_mass,
            programmed_lineup_mass_t=programmed_mass,
            programmed_calls=calls,
            programmed_to_observed_ratio=ratio,
            status=status,
            evidence_class=evidence_class,
            flags=tuple(flags),
            vessel_level_attribution_allowed=False,
        ))
    return out
