# Adapted from AgroLogMT/models/maritime_readiness.py (main 2026-10-19); review provenance before external release.
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MaritimeRuntimeEvidence:
    security_gate_passed: bool = False
    main_protected: bool = False
    wif_verified: bool = False
    secrets_in_vault: bool = False
    gateway_private_verified: bool = False
    ais_real_rows: bool = False
    ais_five_ports_covered: bool = False
    ais_history_days: float = 0.0
    ais_gap_rate: float | None = None
    lineups_five_ports_fresh: bool = False
    geofences_five_ports_validated: bool = False
    port_call_validation_accuracy: float | None = None
    source_health_operational: bool = False
    eta_oos_samples: int = 0
    eta_beats_baseline: bool = False
    queue_history_days: float = 0.0
    trade_aggregate_sources_ready: bool = False
    alert_dedup_verified: bool = False


@dataclass(frozen=True)
class CapabilityGate:
    capability: str
    status: str
    blockers: tuple[str, ...]
    publication_mode: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _gate(capability: str, checks: dict[str, bool], *, publication_mode: str = "INTERNAL") -> CapabilityGate:
    blockers = tuple(sorted(name for name, passed in checks.items() if not passed))
    return CapabilityGate(
        capability=capability,
        status="PASS" if not blockers else "GATED",
        blockers=blockers,
        publication_mode=publication_mode if not blockers else "BLOCKED",
    )


def maritime_capability_gates(evidence: MaritimeRuntimeEvidence) -> list[CapabilityGate]:
    """Independent Maritime Auditor gates. No aggregate percentage can hide a blocker."""
    base_security = {
        "security_gate": evidence.security_gate_passed,
        "main_branch_protected": evidence.main_protected,
        "wif_verified": evidence.wif_verified,
        "secrets_in_vault": evidence.secrets_in_vault,
        "gateway_private": evidence.gateway_private_verified,
    }
    ais_quality = evidence.ais_gap_rate is not None and 0.0 <= evidence.ais_gap_rate <= 0.05
    port_accuracy = (
        evidence.port_call_validation_accuracy is not None
        and evidence.port_call_validation_accuracy >= 0.95
    )

    gates = [
        _gate("SECURE_RUNTIME", base_security),
        _gate("AIS_CAPTURE", {
            **base_security,
            "real_ais_rows": evidence.ais_real_rows,
            "five_port_coverage": evidence.ais_five_ports_covered,
            "source_health": evidence.source_health_operational,
        }),
        _gate("AIS_HISTORY_7D", {
            "real_ais_rows": evidence.ais_real_rows,
            "history_at_least_7d": evidence.ais_history_days >= 7.0,
            "gap_rate_le_5pct": ais_quality,
        }),
        _gate("LINEUP_FIVE_PORTS", {
            "five_port_lineups_fresh": evidence.lineups_five_ports_fresh,
            "source_health": evidence.source_health_operational,
        }),
        _gate("PORT_CALLS", {
            "five_port_geofences": evidence.geofences_five_ports_validated,
            "real_ais_rows": evidence.ais_real_rows,
            "validation_accuracy_ge_95pct": port_accuracy,
        }),
        _gate("ETA_V1", {
            "port_calls_validated": port_accuracy,
            "oos_samples_ge_100": evidence.eta_oos_samples >= 100,
            "beats_declared_baseline": evidence.eta_beats_baseline,
        }, publication_mode="SHADOW"),
        _gate("QUEUE_V1", {
            "port_calls_validated": port_accuracy,
            "queue_history_at_least_30d": evidence.queue_history_days >= 30.0,
            "five_port_geofences": evidence.geofences_five_ports_validated,
        }, publication_mode="SHADOW"),
        _gate("TRADE_FLOW", {
            "aggregate_trade_sources": evidence.trade_aggregate_sources_ready,
            "lineups_five_ports": evidence.lineups_five_ports_fresh,
        }),
        _gate("ALERTING", {
            "source_health": evidence.source_health_operational,
            "alert_dedup_verified": evidence.alert_dedup_verified,
            "secure_runtime": all(base_security.values()),
        }),
    ]
    return gates


def overall_production_status(evidence: MaritimeRuntimeEvidence) -> dict[str, Any]:
    gates = maritime_capability_gates(evidence)
    core = {"SECURE_RUNTIME", "AIS_CAPTURE", "LINEUP_FIVE_PORTS"}
    core_blocked = [gate.capability for gate in gates if gate.capability in core and gate.status != "PASS"]
    return {
        "status": "PRODUCTION_CORE_READY" if not core_blocked else "PRODUCTION_GATED",
        "core_blockers": core_blocked,
        "capabilities": [gate.to_dict() for gate in gates],
        "rule": "capability gates are independent; no readiness percentage overrides a blocking gate",
    }
