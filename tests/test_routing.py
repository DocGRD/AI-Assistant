"""
Tests for Milestone 10 privacy/task-aware routing + health floor.

Stdlib unittest only. Run with:
    python -m unittest tests.test_routing -v

Builds a ModelRegistry against the seeded registry (google=yes/active,
groq=no/active, groq-8B=no/active, cerebras=no/active, nvidia+openrouter=candidate)
and exercises ModelRegistry.route_order / health directly — no network, no keys.
"""

import tempfile
import unittest
from pathlib import Path

from assistant_core.providers.model_registry import ModelRegistry, UNHEALTHY_THRESHOLD

# The active route keys a router would build from the seeded registry when groq +
# google + cerebras keys are present.
ACTIVE = ["groq", "google", "cerebras", "groq:llama-3.1-8b-instant"]


class RoutingTests(unittest.TestCase):

    def setUp(self):
        # ModelRegistry seeds AI/System/Provider-Registry.md into a temp vault and
        # loads it — same path the router uses at startup. The temp dir needs a
        # .obsidian/ marker to count as a real vault (else seeding is skipped — T3.20).
        self._tmp = tempfile.TemporaryDirectory()
        (Path(self._tmp.name) / ".obsidian").mkdir()
        self.reg = ModelRegistry({"vault_path": self._tmp.name})

    def tearDown(self):
        self._tmp.cleanup()

    # ---- privacy ----------------------------------------------------------

    def test_private_excludes_trains_on_data_yes(self):
        order = self.reg.route_order(ACTIVE, private=True, est_tokens=200, response_tokens=500)
        self.assertNotIn("google", order)          # google trains_on_data=yes → excluded
        self.assertIn("groq", order)               # trains_on_data=no → allowed
        self.assertIn("cerebras", order)

    def test_nonprivate_includes_google(self):
        order = self.reg.route_order(ACTIVE, private=False, est_tokens=200, response_tokens=500)
        self.assertIn("google", order)

    # ---- task shape -------------------------------------------------------

    def test_small_default_prefers_groq(self):
        # groq leads everyday short turns (Google's ~20/day free cap made it a poor default).
        order = self.reg.route_order(ACTIVE, private=False, est_tokens=200, response_tokens=500)
        self.assertEqual(order[0], "groq")
        self.assertIn("google", order)                  # still available, just not first

    def test_private_small_prefers_groq(self):
        order = self.reg.route_order(ACTIVE, private=True, est_tokens=200, response_tokens=500)
        self.assertEqual(order[0], "groq")

    def test_large_longform_prefers_high_volume(self):
        # A large request both trips the high-volume path and (via TPM limits)
        # drops the small-TPM groq models, leaving cerebras first.
        order = self.reg.route_order(
            ACTIVE, private=False, est_tokens=20_000, response_tokens=2048, long_form=True
        )
        self.assertTrue(order, "expected at least one provider for a large request")
        self.assertEqual(order[0], "cerebras")

    # ---- candidates never chosen -----------------------------------------

    def test_candidates_never_selected(self):
        # Even if a candidate key is (wrongly) offered as available, status=candidate
        # keeps it out of every order.
        offered = ACTIVE + ["nvidia", "openrouter"]
        for private in (False, True):
            order = self.reg.route_order(offered, private=private, est_tokens=200, response_tokens=500)
            self.assertNotIn("nvidia", order)
            self.assertNotIn("openrouter", order)

    # ---- health floor -----------------------------------------------------

    def test_failures_mark_unhealthy_and_drop_from_routing(self):
        # Healthy first.
        self.assertIn("google", self.reg.route_order(ACTIVE, est_tokens=200, response_tokens=500))
        self.assertTrue(self.reg.error_log.is_healthy("google"))

        # N consecutive real-traffic failures flip it unhealthy.
        for _ in range(UNHEALTHY_THRESHOLD):
            self.reg.error_log.record("google", "other", 0)
        self.assertFalse(self.reg.error_log.is_healthy("google"))

        order = self.reg.route_order(ACTIVE, est_tokens=200, response_tokens=500)
        self.assertNotIn("google", order)          # router stops selecting it

        # A success restores health and routing.
        self.reg.error_log.record_success("google")
        self.assertTrue(self.reg.error_log.is_healthy("google"))
        self.assertIn("google", self.reg.route_order(ACTIVE, est_tokens=200, response_tokens=500))

    def test_floor_drops_below_three_when_two_keys_unhealthy(self):
        self.assertEqual(len(self.reg.healthy_active_provider_keys(ACTIVE)), 3)  # groq, google, cerebras
        for _ in range(UNHEALTHY_THRESHOLD):
            self.reg.error_log.record("google", "other", 0)
            self.reg.error_log.record("cerebras", "other", 0)
        healthy = self.reg.healthy_active_provider_keys(ACTIVE)
        self.assertLess(len(healthy), 3)
        self.assertEqual(healthy, {"groq"})        # only groq's key remains healthy


if __name__ == "__main__":
    unittest.main()
