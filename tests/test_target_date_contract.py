import datetime as dt
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.resolve_target_date import resolve_target, BJ, UTC

class TargetDateContractTest(unittest.TestCase):
    def test_evening_crosses_midnight_without_rolling_twice(self):
        planned = dt.datetime(2026, 10, 15, 12, 7, tzinfo=UTC)  # 20:07 BJT
        actual = dt.datetime(2026, 10, 15, 17, 30, tzinfo=UTC)
        result = resolve_target(mode="evening", event="schedule", schedule="7 12 * * *", actual_started=actual, run_created=planned)
        self.assertEqual(result["target_list_date"], "2026-10-16")
        self.assertEqual(result["planned_slot"], "evening")
        delayed = dt.datetime(2026, 10, 15, 17, 0, tzinfo=UTC)  # 01:00 next BJT day
        result = resolve_target(mode="evening", event="schedule", schedule="7 12 * * *", actual_started=delayed, run_created=delayed)
        self.assertEqual(result["target_list_date"], "2026-10-16")

    def test_stale_scheduled_run_is_blocked(self):
        planned = dt.datetime(2026, 10, 15, 12, 7, tzinfo=UTC)
        actual = dt.datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
        with self.assertRaises(ValueError):
            resolve_target(mode="evening", event="schedule", schedule="7 12 * * *", actual_started=actual, run_created=planned)

    def test_explicit_target_wins(self):
        actual = dt.datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
        result = resolve_target(mode="evening", event="workflow_dispatch", schedule="", actual_started=actual, run_created=None, explicit_target="2026-10-20", explicit_planned_bjt="2026-10-19T20:07:00+08:00")
        self.assertEqual(result["target_list_date"], "2026-10-20")
        self.assertEqual(result["date_source"], "explicit_target_date")

if __name__ == "__main__":
    unittest.main()
