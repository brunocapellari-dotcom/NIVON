# Adapted from AgroLogMT/models/maritime_final_readiness.py (main 2026-10-19); review provenance before external release.
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


# The Maritime product is released as one system. Individual domains may expose
# diagnostics, but no collection of partial/module states is promoted to FINAL_READY.
REQUIRED_FINAL_GATES: tuple[str, ...] = (
    "repository_full_tests",
    "security_gate",
    "supply_chain_gate",
    "branch_protection",
    "wif_least_privilege",
    "secrets_externalized",
    "gateway_private",
    "ais_live_five_ports",
    "ais_quality_validated",
    "stream_resilience_validated",
    "vessel_identity_validated",
    "lineup_five_ports_fresh",
    "geofences_five_ports_validated",
    "port_calls_validation_ge_95pct",
    "eta_out_of_sample_validated",
    "queue_models_history_gate",
    "marine_weather_governed",
    "trade_flow_governed",
    "source_health_operational",
    "storage_backup_restore_tested",
    "incident_response_tested",
    "seven_day_end_to_end_homologation",
)


@dataclass(frozen=True)
class GateEvidence:
    gate: str
    passed: bool
    evidence_ref: str
    measured_at: str
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MaritimeFinalReadiness:
    status: str
    required_gates: tuple[str, ...]
    passed_gates: tuple[str, ...]
    blocked_gates: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @property
    def final_ready(self) -> bool:
        return self.status == "FINAL_READY"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "final_ready": self.final_ready,
            "required_gates": list(self.required_gates),
            "passed_gates": list(self.passed_gates),
            "blocked_gates": list(self.blocked_gates),
            "evidence_refs": list(self.evidence_refs),
        }


def evaluate_final_readiness(evidence: Iterable[GateEvidence]) -> MaritimeFinalReadiness:
    rows = list(evidence)
    by_gate: dict[str, GateEvidence] = {}
    for row in rows:
        if row.gate not in REQUIRED_FINAL_GATES:
            raise ValueError(f"gate Maritime desconhecido: {row.gate}")
        if not row.evidence_ref.strip() or not row.measured_at.strip():
            raise ValueError(f"gate {row.gate} exige evidence_ref e measured_at")
        # Fail closed on duplicate/ambiguous evidence. The caller must reconcile it.
        if row.gate in by_gate:
            raise ValueError(f"evidencia duplicada para gate: {row.gate}")
        by_gate[row.gate] = row

    passed = tuple(g for g in REQUIRED_FINAL_GATES if g in by_gate and by_gate[g].passed)
    blocked = tuple(g for g in REQUIRED_FINAL_GATES if g not in by_gate or not by_gate[g].passed)
    refs = tuple(by_gate[g].evidence_ref for g in REQUIRED_FINAL_GATES if g in by_gate)
    return MaritimeFinalReadiness(
        status="FINAL_READY" if not blocked else "BLOCKED",
        required_gates=REQUIRED_FINAL_GATES,
        passed_gates=passed,
        blocked_gates=blocked,
        evidence_refs=refs,
    )
