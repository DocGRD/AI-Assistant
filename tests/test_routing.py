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

    # ---- M30: capability/tier-aware task routing --------------------------

    def test_no_task_preserves_default_order(self):
        # Task-aware ranking must be neutral when no task is passed (M10 order intact).
        base = self.reg.route_order(ACTIVE, private=False, est_tokens=200, response_tokens=500)
        chat = self.reg.route_order(ACTIVE, private=False, est_tokens=200, response_tokens=500, task="chat")
        self.assertEqual(base[0], "groq")
        self.assertEqual(base, chat)   # "chat" profile is neutral too

    def test_qa_task_keeps_small_model_last(self):
        # A factual QA turn should not lead with the tiny 8B model; larger tiers rank first.
        order = self.reg.route_order(ACTIVE, private=False, est_tokens=200, response_tokens=500, task="qa")
        self.assertTrue(order)
        self.assertNotEqual(order[0], "groq:llama-3.1-8b-instant")   # small never first for QA
        # the 8B (small tier) is ranked after at least one large-tier model
        self.assertGreater(order.index("groq:llama-3.1-8b-instant"), 0)

    # ---- M43 tool-reliable routing ---------------------------------------

    def test_is_reasoning_model(self):
        from assistant_core.providers.model_registry import is_reasoning_model
        for mid in ("gpt-oss-120b", "openai/gpt-oss-20b", "deepseek-r1", "qwq-32b",
                    "magistral-small", "o3-mini", "some-reasoning-model"):
            self.assertTrue(is_reasoning_model(mid), mid)
        for mid in ("llama-3.3-70b-versatile", "gemini-2.5-flash", "llama-4-maverick",
                    "qwen3-32b", "llama-3.1-8b-instant"):
            self.assertFalse(is_reasoning_model(mid), mid)

    def test_require_tools_drops_small_and_reasoning(self):
        from assistant_core.providers.model_registry import is_reasoning_model
        order = self.reg.route_order(ACTIVE, private=False, est_tokens=200,
                                     response_tokens=500, require_tools=True)
        self.assertTrue(order)                                   # still has options
        for k in order:
            spec = self.reg.specs[k]
            self.assertNotEqual(spec.tier, "small", f"{k} is small — should be filtered")
            self.assertFalse(is_reasoning_model(spec.model_id), f"{k} is a reasoning model")
        self.assertNotIn("groq:llama-3.1-8b-instant", order)    # the 8B is small → gone

    def test_require_tools_degrades_when_no_reliable(self):
        # If ONLY a small model is available, don't return empty — degrade to it so the
        # turn still answers (better a mangled reply than a hard failure).
        order = self.reg.route_order(["groq:llama-3.1-8b-instant"], private=False,
                                     est_tokens=200, response_tokens=500, require_tools=True)
        self.assertEqual(order, ["groq:llama-3.1-8b-instant"])

    def test_tier_derivation(self):
        from assistant_core.providers.model_registry import derive_tier
        self.assertEqual(derive_tier("llama-3.1-8b-instant"), "small")
        self.assertEqual(derive_tier("qwen3-32b"), "mid")
        self.assertEqual(derive_tier("llama-3.3-70b-versatile"), "large")
        self.assertEqual(derive_tier("gpt-oss-120b"), "large")
        self.assertEqual(derive_tier("llama-4-maverick-17b-128e-instruct"), "large")

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


class PromptTierTests(unittest.TestCase):
    """M30 — tier-aware prompt addenda appended to the selected model's system prompt."""

    def test_small_gets_hard_anti_invention_rules(self):
        from assistant_core.providers.provider_router import tier_addendum
        small = tier_addendum("small")
        self.assertIn("NEVER invent", small)
        self.assertIn("I don't know", small)
        self.assertIn("[[wikilinks]]", small)

    def test_large_gets_no_addendum(self):
        from assistant_core.providers.provider_router import tier_addendum
        self.assertEqual(tier_addendum("large"), "")

    def test_mid_grounds_without_nagging(self):
        from assistant_core.providers.provider_router import tier_addendum
        mid = tier_addendum("mid")
        self.assertIn("Ground your answer", mid)
        self.assertNotIn("STRICT", mid)


class TaskTemperatureTests(unittest.TestCase):
    """M32 — factual tasks clamp the temperature toward deterministic."""

    def test_factual_tasks_capped(self):
        from assistant_core.providers.provider_router import TASK_MAX_TEMP
        self.assertEqual(TASK_MAX_TEMP["math"], 0.0)
        self.assertLessEqual(TASK_MAX_TEMP["verify"], 0.3)
        self.assertLessEqual(TASK_MAX_TEMP["qa"], 0.3)
        # chat/creative is not in the map → keeps caller temperature
        self.assertNotIn("chat", TASK_MAX_TEMP)


if __name__ == "__main__":
    unittest.main()
