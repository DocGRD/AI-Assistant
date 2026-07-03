"""M16.7 — weekly discovery scheduler decision + discovery job. Stdlib unittest."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from assistant_core.scheduler import discovery_due, _read_last_run, _write_last_run
from assistant_core.providers.discovery_job import run_discovery_proposal


class DiscoveryDueTests(unittest.TestCase):
    def _at(self, hour, day=15):
        return datetime(2026, 7, day, hour, 0, 0)

    def test_only_fires_in_night_hour(self):
        self.assertFalse(discovery_due(self._at(14), None, 7, 3))   # 2pm, not the hour
        self.assertTrue(discovery_due(self._at(3), None, 7, 3))     # 3am, never run → fire

    def test_waits_for_interval(self):
        now = self._at(3, day=15)
        recent = now - timedelta(days=2)
        old    = now - timedelta(days=8)
        self.assertFalse(discovery_due(now, recent, 7, 3))          # only 2 days ago
        self.assertTrue(discovery_due(now, old, 7, 3))              # 8 days ago → due

    def test_state_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "discovery_state.json"
            when = datetime(2026, 7, 15, 3, 0, 0)
            _write_last_run(when, p)
            self.assertEqual(_read_last_run(p), when)
        self.assertIsNone(_read_last_run(Path(d) / "gone.json"))     # missing → None


class DiscoveryJobTests(unittest.TestCase):
    def test_no_providers_is_graceful(self):
        with tempfile.TemporaryDirectory() as d:
            # vault exists but has no registry → no providers
            ok, msg = run_discovery_proposal(d, {}, list_fn=lambda *a, **k: [])
            self.assertFalse(ok)
            self.assertIn("no providers", msg.lower())

    def test_writes_proposal_with_fake_models(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            reg = vault / "AI" / "System" / "Provider-Registry.md"
            reg.parent.mkdir(parents=True, exist_ok=True)
            reg.write_text(
                "| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | "
                "trains_on_data | status | strengths | notes |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| groq | https://api.groq.com/openai/v1 | llama-3.3-70b-versatile | 128000 | 6000 | "
                "30 | 1000 | ? | no | active | reasoning | hand note |\n",
                encoding="utf-8",
            )
            # fake /models: one new chat model + one embedding model
            def fake_list(base_url, api_key):
                return ["llama-3.3-70b-versatile", "text-embedding-3-small"]

            ok, msg = run_discovery_proposal(vault, {"groq_api_key": "x"}, list_fn=fake_list)
            self.assertTrue(ok, msg)
            proposed = (vault / "AI" / "System" / "Provider-Registry-proposed.md").read_text(encoding="utf-8")
            self.assertIn("llama-3.3-70b-versatile", proposed)
            self.assertIn("Specialized / non-chat", proposed)        # embedding kept separately
            self.assertIn("text-embedding-3-small", proposed)


if __name__ == "__main__":
    unittest.main()
