"""Maritime scientific validation: temporal out-of-sample baseline comparison.

No model is promoted to production here. Predictions must have been committed
before the outcomes and must carry dated feature and training provenance.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import mean, median, stdev
from typing import Iterable


def _time(value: str | datetime, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field}: timestamp invalido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field}: timezone obrigatorio")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class MaritimeForecastCase:
    model_id: str
    fold_id: str
    port_id: str
    metric: str
    predicted_at: str
    target_at: str
    outcome_recorded_at: str
    training_cutoff_at: str
    latest_feature_published_at: str
    actual_value: float
    candidate_value: float
    baseline_value: float
    source_id: str
    outcome_evidence: str = "OBSERVADO_OFICIAL"
    quality_status: str = "VALIDATED"
    oos_frozen_before_outcome: bool = False

    def validate(self, as_of: datetime) -> None:
        if self.metric not in {"ETA_ERROR_HOURS", "QUEUE_COUNT"}:
            raise ValueError("metrica desconhecida")
        if not self.model_id.strip() or not self.fold_id.strip() or not self.port_id.strip() or not self.source_id.strip():
            raise ValueError("identidades e fonte obrigatorias")
        if self.quality_status != "VALIDATED" or self.outcome_evidence != "OBSERVADO_OFICIAL":
            raise ValueError("previsao sem qualidade/evidencia oficial para benchmark")
        if not self.oos_frozen_before_outcome:
            raise ValueError("previsao OOS congelada antes do resultado nao demonstrada")
        predicted = _time(self.predicted_at, "predicted_at")
        target = _time(self.target_at, "target_at")
        outcome = _time(self.outcome_recorded_at, "outcome_recorded_at")
        trained = _time(self.training_cutoff_at, "training_cutoff_at")
        published = _time(self.latest_feature_published_at, "latest_feature_published_at")
        if not (trained <= published <= predicted < target <= outcome <= as_of):
            raise ValueError("look-ahead, alvo futuro ou ordem temporal inconsistente")
        for v in (self.actual_value, self.candidate_value, self.baseline_value):
            if isinstance(v, bool) or not math.isfinite(float(v)):
                raise ValueError("resultado nao finito")
            if self.metric == "QUEUE_COUNT" and float(v) < 0:
                raise ValueError("fila nao pode ser negativa")


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    x = sorted(values)
    idx = min(len(x) - 1, max(0, math.ceil((len(x) - 1) * p)))
    return x[idx]


def evaluate_maritime_forecasts(
    cases: Iterable[MaritimeForecastCase], *, as_of: str | datetime,
    minimum_samples: int = 100, minimum_folds: int = 3,
    minimum_improvement_pct: float = 5.0,
) -> dict:
    """Paired prequential evaluation with conservative fold-level confidence.

    Accepts timestamped historical predictions, NOT post-hoc fitted values.
    Release remains prohibited even when the shadow statistical gate wins.
    """
    cutoff = _time(as_of, "as_of")
    if minimum_samples < 30 or minimum_folds < 3 or not 0 < minimum_improvement_pct < 100:
        raise ValueError("thresholds fora das faixas de controle")
    rows = list(cases)
    if not rows:
        return {
            "status": "DATA_GATED", "samples": 0, "folds": 0,
            "candidate_mae": None, "baseline_mae": None,
            "publication_allowed": False, "flags": ["no_oos_outcomes"],
        }
    if len(rows) > 100_000:
        raise ValueError("amostra excessiva")
    for row in rows:
        row.validate(cutoff)
    if len({(r.model_id, r.fold_id, r.port_id, r.metric, r.predicted_at, r.target_at) for r in rows}) != len(rows):
        raise ValueError("observacao de teste duplicada")
    if len({(r.model_id, r.metric) for r in rows}) != 1:
        raise ValueError("mistura de metricas ou versoes de modelo")
    folds: dict[str, list[MaritimeForecastCase]] = defaultdict(list)
    for r in rows:
        folds[r.fold_id].append(r)
    intervals = []
    for fid, group in folds.items():
        starts = [_time(x.predicted_at, "predicted_at") for x in group]
        intervals.append((min(starts), max(starts), fid))
    intervals.sort()
    for left, right in zip(intervals, intervals[1:]):
        if right[0] <= left[1]:
            raise ValueError("folds OOS temporalmente sobrepostos")
    abs_candidate = [abs(r.candidate_value - r.actual_value) for r in rows]
    abs_baseline = [abs(r.baseline_value - r.actual_value) for r in rows]
    candidate_mae, baseline_mae = mean(abs_candidate), mean(abs_baseline)
    gain_pct = (100 * (baseline_mae - candidate_mae) / baseline_mae if baseline_mae > 0 else None)
    fold_rows = []
    paired_gains = []
    for _, _, fid in intervals:
        group = folds[fid]
        c = mean(abs(r.candidate_value - r.actual_value) for r in group)
        b = mean(abs(r.baseline_value - r.actual_value) for r in group)
        improvement = b - c
        paired_gains.append(improvement)
        fold_rows.append({"fold": fid, "n": len(group),
                          "candidate_mae": round(c, 6), "baseline_mae": round(b, 6),
                          "paired_mae_gain": round(improvement, 6)})
    # Lower bound over folds, not individual correlated observations.
    # t critical 95% one-sided for df 2/3/4/5; 1.645 asymptotically.
    critical = {2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015}.get(len(folds)-1, 1.96)
    lower = (mean(paired_gains) - critical * stdev(paired_gains)/math.sqrt(len(folds))
             if len(folds) >= 3 else None)
    flags = []
    if len(rows) < minimum_samples:
        flags.append("insufficient_out_of_sample_cases")
    if len(folds) < minimum_folds:
        flags.append("insufficient_independent_folds")
    if gain_pct is None or gain_pct < minimum_improvement_pct:
        flags.append("no_material_mae_improvement")
    if lower is None or lower <= 0:
        flags.append("paired_fold_lower_bound_not_positive")
    if any(x <= 0 for x in paired_gains):
        flags.append("baseline_not_beaten_in_every_fold")
    return {
        "status": "SHADOW_BASELINE_WIN" if not flags else "DATA_GATED",
        "model_id": rows[0].model_id, "metric": rows[0].metric,
        "samples": len(rows), "folds": len(folds),
        "candidate_mae": round(candidate_mae, 6),
        "baseline_mae": round(baseline_mae, 6),
        "candidate_rmse": round(math.sqrt(mean([(r.candidate_value-r.actual_value)**2 for r in rows])), 6),
        "baseline_rmse": round(math.sqrt(mean([(r.baseline_value-r.actual_value)**2 for r in rows])), 6),
        "candidate_median_abs_error": round(median(abs_candidate), 6),
        "candidate_p90_abs_error": round(_percentile(abs_candidate, .9), 6),
        "improvement_pct": round(gain_pct, 4) if gain_pct is not None else None,
        "fold_paired_gain_lower_95": round(lower, 6) if lower is not None else None,
        "fold_details": fold_rows, "flags": flags,
        "publication_allowed": False, "model_promoted": False,
        "method": "frozen_prequential_oos_paired_fold_comparison",
        "limitations": [
            "model predictions/outcomes require independently confirmed archive",
            "time-correlated and port-correlated observations need external audit",
            "shadow baseline win is not operational model approval",
        ],
    }
