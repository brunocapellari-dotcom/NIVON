"""Testes sinteticos da integracao hidrologia/agro/logistica do Maritime."""
import unittest
from datetime import datetime, timedelta, timezone

from nivon.maritime.cross_domain import CrossDomainSignal, evaluate_cross_domain
from nivon.maritime.intelligence import MaritimeAnalysisRequest, MaritimeIntelligenceCoordinator

NOW = datetime(2026, 10, 19, 15, tzinfo=timezone.utc)


def metric(name, **kw):
    args = dict(metric_id=name, scope_id="SANTAREM", value=1.0,
                unit="event" if "RESTRICTION" in name else "mm",
                source_id="OFICIAL_FIXTURE", reference_at=NOW.isoformat(),
                evidence_class="OBSERVADO", quality_status="VALIDATED",
                derivation_authorized=True)
    args.update(kw)
    return CrossDomainSignal(**args)


class TestCrossDomain(unittest.TestCase):
    def evaluate(self, *signals, queue="DATA_GATED"):
        return evaluate_cross_domain(
            now=NOW, scope_ids=("SANTAREM",), signals=signals, queue_status=queue
        )

    def test_no_publishing_even_with_observations(self):
        result = self.evaluate(metric("RIVER_LEVEL_M"))
        self.assertEqual(len(result["facts"]), 1)
        self.assertFalse(result["publication_allowed"])
        self.assertFalse(result["hypotheses"])

    def test_river_level_does_not_prove_navigation_restriction(self):
        result = self.evaluate(metric("RIVER_LEVEL_M"), queue="SHADOW_READY")
        self.assertFalse(result["hypotheses"])

    def test_explicit_restriction_and_port_pressure_create_hypothesis(self):
        result = self.evaluate(metric("HYDRO_RESTRICTION_OFFICIAL"),
                               queue="SHADOW_READY")
        self.assertEqual(result["hypotheses"][0]["publication_status"], "HYPOTHESIS_ONLY")

    def test_no_rights_excludes_signal(self):
        result = self.evaluate(metric("RIVER_LEVEL_M", derivation_authorized=False))
        self.assertEqual(len(result["facts"]), 0)
        self.assertEqual(result["rejected"][0]["reason"], "derivation_rights_missing")

    def test_stale_signal_excluded(self):
        result = self.evaluate(metric(
            "RAINFALL_MM_24H",
            reference_at=(NOW-timedelta(days=3)).isoformat(),
            max_age_hours=24,
        ))
        self.assertEqual(result["rejected"][0]["reason"], "source_stale")

    def test_outside_scope_excluded(self):
        result = self.evaluate(metric("RIVER_LEVEL_M", scope_id="ITAQUI"))
        self.assertEqual(result["rejected"][0]["reason"], "scope_not_joined")

    def test_freight_announcement_not_quote(self):
        result = self.evaluate(
            metric("FREIGHT_ANNOUNCED_BRL_T", unit="BRL/t", value=230),
            metric("EXPORT_PROGRAMMED_T", unit="t", value=9000),
        )
        self.assertEqual(result["hypotheses"][0]["type"], "FREIGHT_EXPORT_AGRO_CONTEXT")
        self.assertIn("sem previsao ou preco negociado", result["hypotheses"][0]["message"])

    def test_coordinator_exposes_context_without_publishing(self):
        request = MaritimeAnalysisRequest(
            port_id="SANTAREM", now=NOW,
            cross_domain_signals=(metric("RIVER_LEVEL_M"),),
        )
        result = MaritimeIntelligenceCoordinator().run(request)
        self.assertEqual(len(result["cross_domain"]["facts"]), 1)
        self.assertFalse(result["publication_allowed"])


if __name__ == "__main__":
    unittest.main()
