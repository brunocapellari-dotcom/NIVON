"""Backtest maritimo sintetico; evita look-ahead e metricas infladas."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from nivon.maritime.model_validation import MaritimeForecastCase, evaluate_maritime_forecasts

START = datetime(2025, 1, 1, tzinfo=timezone.utc)
AS_OF = datetime(2026, 10, 19, tzinfo=timezone.utc)


def case(fold=0, index=0, *, candidate=1.0, baseline=6.0, metric="ETA_ERROR_HOURS"):
    predicted = START + timedelta(days=fold*40, minutes=index*10)
    return MaritimeForecastCase(
        model_id="NIVON_ETA_SHADOW_V1", fold_id=f"fold-{fold+1}",
        port_id="SANTOS", metric=metric,
        predicted_at=predicted.isoformat(),
        target_at=(predicted+timedelta(days=2)).isoformat(),
        outcome_recorded_at=(predicted+timedelta(days=2, hours=1)).isoformat(),
        training_cutoff_at=(predicted-timedelta(days=7)).isoformat(),
        latest_feature_published_at=(predicted-timedelta(hours=1)).isoformat(),
        actual_value=0.0, candidate_value=candidate, baseline_value=baseline,
        source_id="PORT_AUTHORITY_TEST_FIXTURE",
        outcome_evidence="OBSERVADO_OFICIAL",
        quality_status="VALIDATED",
        oos_frozen_before_outcome=True,
    )


def sample():
    return [case(fold, i) for fold in range(3) for i in range(40)]


class MaritimeScientificTest(unittest.TestCase):
    def evaluate(self, rows):
        return evaluate_maritime_forecasts(rows, as_of=AS_OF)

    def test_no_data_does_not_become_zero_mae(self):
        r = self.evaluate([])
        self.assertEqual(r["status"], "DATA_GATED")
        self.assertIsNone(r["candidate_mae"])
        self.assertFalse(r["publication_allowed"])

    def test_good_frozen_oos_wins_baseline_but_stays_shadow(self):
        r = self.evaluate(sample())
        self.assertEqual(r["status"], "SHADOW_BASELINE_WIN")
        self.assertEqual(r["samples"], 120)
        self.assertEqual(r["folds"], 3)
        self.assertEqual(r["candidate_mae"], 1.0)
        self.assertEqual(r["baseline_mae"], 6.0)
        self.assertGreater(r["improvement_pct"], 80)
        self.assertFalse(r["publication_allowed"])
        self.assertFalse(r["model_promoted"])

    def test_weak_sample_stays_gated(self):
        r = self.evaluate(sample()[:30])
        self.assertIn("insufficient_out_of_sample_cases", r["flags"])
        self.assertIn("insufficient_independent_folds", r["flags"])

    def test_bad_candidate_does_not_pass(self):
        r = self.evaluate([replace(x, candidate_value=10.0) for x in sample()])
        self.assertEqual(r["status"], "DATA_GATED")
        self.assertIn("no_material_mae_improvement", r["flags"])

    def test_no_evidence_cannot_enter_benchmark(self):
        with self.assertRaises(ValueError):
            self.evaluate([replace(case(), quality_status="UNVALIDATED")])
        with self.assertRaises(ValueError):
            self.evaluate([replace(case(), outcome_evidence="INFERIDO_AIS")])

    def test_future_feature_or_training_leaks_blocked(self):
        x = case()
        with self.assertRaises(ValueError):
            self.evaluate([replace(x, latest_feature_published_at=x.target_at)])
        with self.assertRaises(ValueError):
            self.evaluate([replace(x, training_cutoff_at=x.target_at)])

    def test_candidate_not_frozen_before_outcome_blocked(self):
        with self.assertRaises(ValueError):
            self.evaluate([replace(case(), oos_frozen_before_outcome=False)])

    def test_non_timezone_event_blocked(self):
        with self.assertRaises(ValueError):
            self.evaluate([replace(case(), predicted_at="2025-01-01T00:00:00")])

    def test_duplicate_predictions_blocked(self):
        x = case()
        with self.assertRaises(ValueError):
            self.evaluate([x, x])

    def test_overlapping_folds_blocked(self):
        x, y = case(0), case(1)
        overlapping = replace(y, predicted_at=x.predicted_at)
        with self.assertRaises(ValueError):
            self.evaluate([x, overlapping])

    def test_wrong_metric_mix_blocked(self):
        with self.assertRaises(ValueError):
            self.evaluate([case(0), case(1, metric="QUEUE_COUNT")])

    def test_negative_queue_count_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate([case(metric="QUEUE_COUNT", candidate=-1)])

    def test_outcome_not_yet_known(self):
        future = case(0)
        early = START + timedelta(days=1)
        with self.assertRaises(ValueError):
            evaluate_maritime_forecasts([future], as_of=early)


if __name__ == "__main__":
    unittest.main()
