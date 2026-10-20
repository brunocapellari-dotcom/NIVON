# Adapted from AgroLogMT/models/maritime_anomaly.py (main 2026-10-19); review provenance before external release.
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


_SEVERITY_ORDER = {"INFO": 10, "LOW": 20, "MEDIUM": 30, "HIGH": 40, "CRITICAL": 50}


@dataclass(frozen=True)
class MaritimeAnomaly:
    anomaly_type: str
    severity: str
    confidence: float
    evidence_class: str
    summary: str
    evidence: tuple[str, ...]
    action: str
    publication_status: str = "ALERTABLE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def detect_maritime_anomalies(
    *,
    ais_quality_flags: Iterable[str] = (),
    spoofing_suspected: bool = False,
    source_health_status: str | None = None,
    eta_deviation_hours: float | None = None,
    queue_zscore: float | None = None,
    queue_percentile: float | None = None,
    reconciliation_flags: Iterable[str] = (),
    corroborated_ais: bool = False,
) -> list[MaritimeAnomaly]:
    """Create auditable operational anomalies from explicit deterministic signals.

    The engine never labels AIS spoofing as confirmed. A spoofing suspicion is only an
    alertable hypothesis and requires corroboration by independent evidence for any
    higher-level operational conclusion.
    """
    findings: list[MaritimeAnomaly] = []
    quality = set(ais_quality_flags)
    reconciliation = set(reconciliation_flags)

    severe_track = quality & {
        "teleport",
        "impossible_speed",
        "reported_impossible_speed",
        "clock_anomaly_non_monotonic",
        "identity_conflict_mmsi_to_imo",
    }
    if severe_track:
        severity = "HIGH" if len(severe_track) >= 2 else "MEDIUM"
        findings.append(MaritimeAnomaly(
            anomaly_type="AIS_TRACK_INTEGRITY",
            severity=severity,
            confidence=_bounded(0.70 + 0.08 * min(3, len(severe_track))),
            evidence_class="OBSERVADO",
            summary="Trajetória AIS contém sinais incompatíveis com movimento físico ou identidade estável.",
            evidence=tuple(sorted(severe_track)),
            action="Quarentenar a mensagem e exigir sequência AIS consistente antes de atualizar estado físico.",
        ))

    if spoofing_suspected:
        evidence = tuple(sorted(severe_track)) or ("multi_signal_anomaly",)
        findings.append(MaritimeAnomaly(
            anomaly_type="AIS_SPOOFING_SUSPECTED",
            severity="HIGH",
            confidence=0.75 if corroborated_ais else 0.60,
            evidence_class="INFERIDO",
            summary="Há indícios compatíveis com spoofing AIS; não há confirmação automática.",
            evidence=evidence,
            action="Cruzar com mensagens subsequentes, identidade, radar/porto e outras fontes independentes.",
            publication_status="HYPOTHESIS_ONLY",
        ))

    health = str(source_health_status or "").strip().upper()
    if health in {"UNHEALTHY", "STALE", "NO_DATA"}:
        severity = "HIGH" if health == "UNHEALTHY" else "MEDIUM"
        findings.append(MaritimeAnomaly(
            anomaly_type="SOURCE_HEALTH",
            severity=severity,
            confidence=1.0,
            evidence_class="OBSERVADO",
            summary=f"Fonte marítima está em estado {health}.",
            evidence=(f"source_health={health}",),
            action="Bloquear promoção de indicadores dependentes da fonte e acionar fallback autorizado quando existir.",
        ))

    if eta_deviation_hours is not None:
        deviation = float(eta_deviation_hours)
        abs_dev = abs(deviation)
        if abs_dev >= 24:
            severity = "HIGH"
        elif abs_dev >= 12:
            severity = "MEDIUM"
        elif abs_dev >= 6:
            severity = "LOW"
        else:
            severity = "INFO"
        if abs_dev >= 6:
            direction = "atraso" if deviation > 0 else "antecipação"
            findings.append(MaritimeAnomaly(
                anomaly_type="ETA_DEVIATION",
                severity=severity,
                confidence=0.90 if corroborated_ais else 0.65,
                evidence_class="ESTIMADO",
                summary=f"ETA proprietário indica {direction} material frente à programação informada.",
                evidence=(f"eta_deviation_hours={deviation:.2f}",),
                action="Recalcular impacto em fila, berço e programação do terminal; manter intervalo de incerteza visível.",
            ))

    queue_signals: list[str] = []
    if queue_zscore is not None and float(queue_zscore) >= 2.0:
        queue_signals.append(f"queue_zscore={float(queue_zscore):.2f}")
    if queue_percentile is not None and float(queue_percentile) >= 0.90:
        queue_signals.append(f"queue_percentile={float(queue_percentile):.3f}")
    if queue_signals:
        high = (queue_zscore is not None and float(queue_zscore) >= 3.0) or (
            queue_percentile is not None and float(queue_percentile) >= 0.98
        )
        findings.append(MaritimeAnomaly(
            anomaly_type="PORT_QUEUE_PRESSURE",
            severity="HIGH" if high else "MEDIUM",
            confidence=0.85 if len(queue_signals) >= 2 else 0.70,
            evidence_class="INFERIDO",
            summary="Fila portuária está significativamente acima do regime histórico informado ao modelo.",
            evidence=tuple(queue_signals),
            action="Avaliar aproximações, capacidade de berço, clima, line-up e congestionamento terrestre associado.",
        ))

    conflict_flags = reconciliation & {
        "ais_port_divergence",
        "terminal_divergence",
        "lineup_says_berthed_but_ais_waiting",
        "lineup_realized_not_confirmed",
    }
    if conflict_flags:
        findings.append(MaritimeAnomaly(
            anomaly_type="AIS_LINEUP_CONFLICT",
            severity="MEDIUM",
            confidence=0.90,
            evidence_class="INFERIDO",
            summary="AIS e informação portuária apresentam divergência operacional relevante.",
            evidence=tuple(sorted(conflict_flags)),
            action="Manter fontes separadas, não promover programação a realizado e aguardar reconciliação/confirmação oficial.",
        ))

    findings.sort(key=lambda item: (-_SEVERITY_ORDER[item.severity], item.anomaly_type))
    return findings
