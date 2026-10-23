"""Testes da janela noturna MT: execução autônoma só de noite."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from nivon import janela_noturna as noite
from nivon import autonomia


class TestJanelaNoturna(unittest.TestCase):
    @staticmethod
    def local(hour, minute=0, day=23):
        return datetime(2026, 10, day, hour, minute, tzinfo=noite.VALID_ZONE)

    def test_outside_window(self):
        for hour in (6, 7, 12, 19):
            self.assertFalse(noite.window(self.local(hour))["active"])
            self.assertFalse(noite.may_begin(self.local(hour)))
        self.assertFalse(noite.window(self.local(19, 59))["active"])

    def test_night_window_across_midnight(self):
        for hour in (20, 21, 23, 0, 1, 5):
            self.assertTrue(noite.window(self.local(hour))["active"])
        self.assertEqual(noite.window(self.local(23))["closes"].hour, 6)
        self.assertEqual(noite.window(self.local(23))["closes"].day, 24)
        self.assertEqual(noite.window(self.local(4))["closes"].day, 23)

    def test_early_morning_guard_accounts_for_testing(self):
        self.assertTrue(noite.may_begin(self.local(5, 20), per_task_minutes=15))
        self.assertFalse(noite.may_begin(self.local(5, 31), per_task_minutes=15))
        self.assertEqual(noite.minutes_left(self.local(5, 45)), 15)

    def test_timezone_is_cuiaba(self):
        utc = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)
        result = noite.status(utc)
        self.assertEqual(result["timezone"], "America/Cuiaba")
        self.assertTrue(result["active"])
        self.assertEqual(result["window"], "20:00-06:00")

    def test_naive_time_rejected_and_duration_validated(self):
        with self.assertRaises(ValueError):
            noite.window(datetime(2026, 10, 23, 22))
        for n in (1, 61):
            with self.assertRaises(ValueError):
                noite.may_begin(self.local(21), per_task_minutes=n)

    def test_supervisor_never_runs_at_midday(self):
        with patch.object(autonomia, "may_begin", return_value=False), \
             patch.object(autonomia, "preflight") as preflight:
            with self.assertRaisesRegex(RuntimeError, "somente"):
                autonomia.run()
            preflight.assert_not_called()
        with patch.object(autonomia, "may_begin", return_value=False), \
             patch.object(autonomia, "preflight") as preflight:
            self.assertEqual(autonomia.main(["start"]), 2)
            preflight.assert_not_called()


if __name__ == "__main__":
    unittest.main()
