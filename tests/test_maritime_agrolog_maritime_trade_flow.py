# Tests adapted from AgroLogMT/tests/test_maritime_trade_flow.py (2026-10-19).
import unittest

from nivon.maritime.maritime_trade_flow import (
    LineupAggregate,
    PortTradeAggregate,
    build_trade_flow_signals,
)


class MaritimeTradeFlowTests(unittest.TestCase):
    def test_aggregate_join_never_authorizes_vessel_attribution(self):
        signals = build_trade_flow_signals(
            [PortTradeAggregate("SANTOS", "2026-08", "SOJA", 1_000_000, "comexstat")],
            [LineupAggregate("SANTOS", "2026-08", "SOJA", 900_000, 15, "aps")],
        )
        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.status, "AGGREGATE_CONFRONTED")
        self.assertFalse(signal.vessel_level_attribution_allowed)
        self.assertEqual(signal.evidence_class, "INFERIDO")
        self.assertAlmostEqual(signal.programmed_to_observed_ratio or 0, 0.9)

    def test_programming_only_remains_informed(self):
        signals = build_trade_flow_signals(
            [],
            [LineupAggregate("PARANAGUA", "2026-09", "MILHO", 100_000, 2, "ports-pr")],
        )
        signal = signals[0]
        self.assertEqual(signal.status, "PROGRAMMED_ONLY")
        self.assertEqual(signal.evidence_class, "INFORMADO")
        self.assertIn("observed_trade_missing", signal.flags)

    def test_observed_only_remains_observed(self):
        signal = build_trade_flow_signals(
            [PortTradeAggregate("ITAQUI", "2026-09", "FERTILIZANTE", 50_000, "antaq")],
            [],
        )[0]
        self.assertEqual(signal.status, "OBSERVED_ONLY")
        self.assertEqual(signal.evidence_class, "OBSERVADO")

    def test_negative_mass_fails_closed(self):
        with self.assertRaises(ValueError):
            build_trade_flow_signals(
                [PortTradeAggregate("SANTOS", "2026-08", "SOJA", -1, "comexstat")],
                [],
            )


if __name__ == "__main__":
    unittest.main()
