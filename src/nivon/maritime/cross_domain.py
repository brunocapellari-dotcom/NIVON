"""Cruzamento hidrometeo/agro/frete com portos, sem causalidade inventada."""
from __future__ import annotations
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

_METRICS = {
    "RIVER_LEVEL_M", "NAVIGABLE_DRAFT_M", "HYDRO_RESTRICTION_OFFICIAL",
    "RAINFALL_MM_24H", "ROAD_RESTRICTION_OFFICIAL", "RAIL_INTERRUPTION_OFFICIAL",
    "HARVEST_PROGRESS_PCT", "EXPORT_PROGRAMMED_T", "FREIGHT_ANNOUNCED_BRL_T",
    "DIESEL_BRL_L", "PORT_MOVEMENT_OBSERVED_T",
}
_VALID_EVIDENCE = {"OBSERVADO", "INFORMADO", "ESTIMADO", "INFERIDO", "PROJETADO"}


def _utc(value: str | datetime) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError("referencia temporal invalida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone de evidencia obrigatorio")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class CrossDomainSignal:
    metric_id: str
    scope_id: str
    value: float
    unit: str
    source_id: str
    reference_at: str
    evidence_class: str
    quality_status: str = "UNVALIDATED"
    derivation_authorized: bool = False
    max_age_hours: float = 24.0

    def validate(self) -> None:
        if self.metric_id not in _METRICS:
            raise ValueError("metrica nao cadastrada")
        if not self.scope_id.strip() or not self.unit.strip() or not self.source_id.strip():
            raise ValueError("fonte, escopo e unidade obrigatorios")
        if self.evidence_class not in _VALID_EVIDENCE:
            raise ValueError("evidencia invalida")
        if not math.isfinite(float(self.value)):
            raise ValueError("valor nao finito")
        if not 0 < float(self.max_age_hours) <= 8760:
            raise ValueError("janela de validade invalida")
        _utc(self.reference_at)


def evaluate_cross_domain(*, now: str | datetime, scope_ids: Iterable[str],
                          signals: Iterable[CrossDomainSignal],
                          queue_status: str | None = None) -> dict:
    """Fontes elegiveis entram como CONTEXTO, nunca como previsao causal de frete.

    Uma restricao oficial so pode ser citada como informacao da fonte que a publicou;
    nivel de rio por si so nao comprova calado nem restricao de navegacao.
    """
    calculated_at = _utc(now)
    allowed_scopes = {x.strip().upper() for x in scope_ids if x.strip()}
    if not allowed_scopes:
        raise ValueError("escopos conhecidos obrigatorios")
    accepted, excluded = [], []
    for signal in signals:
        signal.validate()
        ref = _utc(signal.reference_at)
        age_h = (calculated_at - ref).total_seconds() / 3600
        reason = None
        if signal.scope_id.strip().upper() not in allowed_scopes:
            reason = "scope_not_joined"
        elif not signal.derivation_authorized:
            reason = "derivation_rights_missing"
        elif signal.quality_status != "VALIDATED":
            reason = "quality_not_validated"
        elif age_h < 0:
            reason = "future_reference"
        elif age_h > signal.max_age_hours:
            reason = "source_stale"
        if reason:
            excluded.append({"metric_id": signal.metric_id, "source_id": signal.source_id,
                             "reason": reason})
        else:
            accepted.append({**asdict(signal), "age_hours": round(age_h, 3)})

    metrics = {x["metric_id"] for x in accepted}
    hypotheses = []
    if queue_status == "SHADOW_READY" and (
        "HYDRO_RESTRICTION_OFFICIAL" in metrics or
        "ROAD_RESTRICTION_OFFICIAL" in metrics or
        "RAIL_INTERRUPTION_OFFICIAL" in metrics
    ):
        hypotheses.append({
            "type": "MULTIMODAL_CONSTRAINT_COINCIDENCE",
            "evidence_class": "INFERIDO",
            "publication_status": "HYPOTHESIS_ONLY",
            "message": "Restricao informada e pressao portuaria coincidem; relacao causal nao demonstrada.",
            "source_ids": sorted({x["source_id"] for x in accepted}),
        })
    if ("FREIGHT_ANNOUNCED_BRL_T" in metrics and
            ("EXPORT_PROGRAMMED_T" in metrics or "HARVEST_PROGRESS_PCT" in metrics)):
        hypotheses.append({
            "type": "FREIGHT_EXPORT_AGRO_CONTEXT",
            "evidence_class": "INFERIDO",
            "publication_status": "HYPOTHESIS_ONLY",
            "message": "Frete anunciado e sinais de safra/exportacao presentes; sem previsao ou preco negociado.",
            "source_ids": sorted({x["source_id"] for x in accepted}),
        })
    return {
        "status": "CONTEXT_ONLY_NO_CAUSAL_FORECAST",
        "publication_allowed": False,
        "facts": accepted,
        "rejected": excluded,
        "hypotheses": hypotheses,
        "rule": "river level != navigable draft; announced freight != negotiated rate",
    }
