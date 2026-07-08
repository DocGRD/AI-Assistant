"""M34 — background resource governor (foreground-priority + hourly budget)."""

import unittest

from assistant_core.background import governor


class ShouldDeferTests(unittest.TestCase):
    def test_defers_while_foreground_active(self):
        # now=100, foreground active until 130 → defer
        self.assertTrue(governor.should_defer(100.0, 130.0, [], hourly_budget=60))
        # after the cooldown → allowed
        self.assertFalse(governor.should_defer(131.0, 130.0, [], hourly_budget=60))

    def test_defers_when_budget_spent(self):
        now = 10_000.0
        calls = [now - i for i in range(60)]      # 60 calls in the last minute
        self.assertTrue(governor.should_defer(now, 0.0, calls, hourly_budget=60))
        self.assertFalse(governor.should_defer(now, 0.0, calls[:59], hourly_budget=60))

    def test_old_calls_fall_out_of_window(self):
        now = 10_000.0
        calls = [now - 4000 for _ in range(100)]  # all older than 1h
        self.assertFalse(governor.should_defer(now, 0.0, calls, hourly_budget=60))


class RunningStateTests(unittest.TestCase):
    def setUp(self):
        governor._reset_for_tests()

    def test_mark_foreground_pauses_then_resumes(self):
        governor.mark_foreground_activity(cooldown_s=30, now=1000.0)
        self.assertTrue(governor.foreground_active(now=1010.0))
        self.assertFalse(governor.foreground_active(now=1031.0))
        self.assertFalse(governor.may_run({"background_hourly_budget": 60}, now=1010.0))  # fg busy
        self.assertTrue(governor.may_run({"background_hourly_budget": 60}, now=1031.0))

    def test_budget_counts_and_recovers(self):
        cfg = {"background_hourly_budget": 3}
        for t in (5000.0, 5001.0, 5002.0):
            governor.record_background_call(now=t)
        self.assertEqual(governor.budget_remaining(3, now=5003.0), 0)
        self.assertFalse(governor.may_run(cfg, now=5003.0))
        # an hour later the window clears
        self.assertTrue(governor.may_run(cfg, now=5003.0 + 3601))


if __name__ == "__main__":
    unittest.main()
