# Reused from AgroLogMT/collector/port_lifecycle.py; verify provenance/license before commercial release.
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Any, Iterable

OFFICIAL_SOURCES = {
    "SANTOS": "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracacoes-programadas/",
    "PARANAGUA": "https://www.portosdoparana.pr.gov.br/Operacional/Pagina/Atas-do-Corredor-de-Exportacao",
    "BARCARENA_VILA_DO_CONDE": "https://www.cdp.com.br/companhia-docas-do-para/programacao-de-navios/",
    "SANTAREM": "https://www.cdp.com.br/companhia-docas-do-para/programacao-de-navios/",
    "ITAQUI": "https://www.portodoitaqui.com/",
}
REQUIRED_SYSTEMS = frozenset(OFFICIAL_SOURCES)
# Historical identifiers remain readable but never satisfy a V1 port-specific readiness gate.
LEGACY_SYSTEMS = frozenset({"PARANAGUA_ANTONINA", "ARCO_NORTE_CDP"})
KNOWN_SYSTEMS = REQUIRED_SYSTEMS | LEGACY_SYSTEMS


class PortCallState(IntEnum):
    PROGRAMADO = 10
    ATRACADO = 20
    DESATRACADO = 30
    CONCLUIDO = 40


@dataclass(frozen=True)
class PortCallObservation:
    port_system: str
    source_url: str
    observed_at: str
    data_referencia: str
    ship_name: str | None = None
    imo: str | None = None
    duv: str | None = None
    terminal: str | None = None
    cargo: str | None = None
    state: str = "PROGRAMADO"
    quantity_programmed_t: float | None = None
    quantity_realized_t: float | None = None
    arrival_at: str | None = None
    berth_at: str | None = None
    unberth_at: str | None = None
    evidence_class: str = "observado"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def event_key(self) -> str:
        identity = self.duv or self.imo or self.ship_name or "unknown"
        return f"{self.port_system}:{identity}".upper().strip()


def _state(value: str) -> PortCallState:
    try:
        return PortCallState[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"estado portuario invalido: {value}") from exc


def validate_observation(row: PortCallObservation) -> None:
    if row.port_system not in KNOWN_SYSTEMS:
        raise ValueError(f"port_system nao canonico: {row.port_system}")
    if not (row.duv or row.imo or row.ship_name):
        raise ValueError("observacao portuaria exige DUV, IMO ou nome do navio")
    state = _state(row.state)
    if row.quantity_programmed_t is not None and row.quantity_programmed_t < 0:
        raise ValueError("quantity_programmed_t negativa")
    if row.quantity_realized_t is not None and row.quantity_realized_t < 0:
        raise ValueError("quantity_realized_t negativa")
    if state < PortCallState.CONCLUIDO and row.quantity_realized_t is not None:
        raise ValueError("tonelagem realizada exige estado CONCLUIDO")


def promote_state(previous: PortCallObservation, current: PortCallObservation) -> PortCallObservation:
    """Validate a lifecycle transition without inventing operational completion.

    A newer scrape cannot promote a call by age alone. The current observation must
    carry the explicit official state. Regressions are blocked; replays are allowed.
    Operational completion can be observed even when the source omits realized tonnage;
    in that case quantity_realized_t stays null rather than being copied from programmed.
    """
    validate_observation(previous)
    validate_observation(current)
    if previous.event_key != current.event_key:
        raise ValueError("event_key diferente na transicao")
    before = _state(previous.state)
    after = _state(current.state)
    if after < before:
        raise ValueError(f"regressao de estado bloqueada: {before.name}->{after.name}")
    if after == PortCallState.ATRACADO and not current.berth_at:
        raise ValueError("ATRACADO exige berth_at oficial")
    if after in {PortCallState.DESATRACADO, PortCallState.CONCLUIDO} and not current.unberth_at:
        raise ValueError(f"{after.name} exige unberth_at oficial")
    return current


def multiport_readiness(
    observations: Iterable[PortCallObservation],
    *,
    now: datetime,
    freshness_hours: int = 96,
) -> dict[str, Any]:
    """Require recent official evidence for every port in the Maritime V1 pilot.

    Vila do Conde and Santarem share the CDP publication surface but remain separate
    readiness systems: evidence for one cannot satisfy the other. Legacy combined
    identifiers remain auditable historical observations but do not satisfy V1 gates.
    """
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=freshness_hours)
    covered: set[str] = set()
    stale: set[str] = set()
    counts: dict[str, int] = {system: 0 for system in KNOWN_SYSTEMS}
    for row in observations:
        validate_observation(row)
        observed = datetime.fromisoformat(row.observed_at.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("observed_at deve ter timezone")
        counts[row.port_system] += 1
        if observed.astimezone(timezone.utc) >= cutoff:
            if row.port_system in REQUIRED_SYSTEMS:
                covered.add(row.port_system)
        else:
            stale.add(row.port_system)
    missing = sorted(REQUIRED_SYSTEMS - covered)
    return {
        "status": "MULTIPORT_VALIDATED" if not missing else "PARTIAL_MULTI_PORT",
        "covered_systems": sorted(covered),
        "missing_or_stale_systems": missing,
        "stale_systems": sorted((stale & REQUIRED_SYSTEMS) - covered),
        "legacy_observations": {
            system: counts[system] for system in sorted(LEGACY_SYSTEMS) if counts[system]
        },
        "counts": counts,
        "required_systems": sorted(REQUIRED_SYSTEMS),
    }
