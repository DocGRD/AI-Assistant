"""Discovery completion probe: classify responses, cap the queue, promote on success."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from assistant_core.providers.discovery_job import run_discovery_proposal
from assistant_core.providers.model_probe import (
    ProbeResult, classify_probe_response, select_probe_rows,
)
from assistant_core.providers.registry_proposer import iter_discovered_rows


def _ok_body(text="pong"):
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]})


class ClassifyProbeTests(unittest.TestCase):
    def test_200_with_content_is_ok(self):
        self.assertEqual(classify_probe_response(200, _ok_body()).outcome, "ok")

    def test_200_empty_is_not_ok(self):
        self.assertEqual(classify_probe_response(200, _ok_body("")).outcome, "failed")

    def test_404_and_decommissioned_are_not_found(self):
        self.assertEqual(classify_probe_response(404, "missing").outcome, "not_found")
        self.assertEqual(
            classify_probe_response(400, '{"error":"model_not_found"}').outcome, "not_found")
        self.assertEqual(
            classify_probe_response(400, "model_decommissioned").outcome, "not_found")

    def test_auth_rate_limit_and_server_error(self):
        self.assertEqual(classify_probe_response(401, "nope").outcome, "auth")
        self.assertEqual(classify_probe_response(403, "nope").outcome, "auth")
        self.assertEqual(classify_probe_response(429, "slow").outcome, "rate_limited")
        self.assertEqual(classify_probe_response(503, "down").outcome, "failed")


class SelectProbeRowsTests(unittest.TestCase):
    def _row(self, provider, mid, prev=None):
        return SimpleNamespace(provider=provider, model_id=mid, norm_id=mid, chat=True, prev=prev)

    def test_active_first_then_preferred_then_other_within_cap(self):
        prev = SimpleNamespace(status="active")
        rows = [
            self._row("nvidia", "nv-new"),
            self._row("groq", "groq-new"),
            self._row("nvidia", "nv-active", prev=prev),
        ]
        picked = select_probe_rows(rows, {"discovery_probe_max": 2,
                                           "discovery_probe_providers": ["groq", "cerebras", "google"]})
        self.assertEqual([r.model_id for r in picked], ["nv-active", "groq-new"])

    def test_other_providers_fill_remaining_budget(self):
        rows = [self._row("nvidia", "nv-new"), self._row("groq", "groq-new")]
        picked = select_probe_rows(rows, {"discovery_probe_max": 2,
                                           "discovery_probe_providers": ["groq"]})
        self.assertEqual([r.model_id for r in picked], ["groq-new", "nv-new"])


class DiscoveryProbeIntegrationTests(unittest.TestCase):
    def test_mock_probe_promotes_bare_google_id_and_summarizes(self):
        seen = []

        def fake_list(base_url, api_key):
            return ["models/gemini-2.5-flash", "embed-me"]

        def fake_probe(base_url, api_key, model_id):
            seen.append(model_id)
            return ProbeResult("ok", "pong")

        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            reg = vault / "AI" / "System" / "Provider-Registry.md"
            reg.parent.mkdir(parents=True)
            reg.write_text(
                "| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | "
                "trains_on_data | status | strengths | notes |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| google | https://generativelanguage.googleapis.com/v1beta/openai | "
                "gemini-2.0-flash | 1000 | ? | ? | ? | ? | yes | active | fast | old |\n",
                encoding="utf-8",
            )
            ok, msg = run_discovery_proposal(
                vault, {"google_api_key": "k"}, list_fn=fake_list, probe_fn=fake_probe, probe=True,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(seen, ["gemini-2.5-flash"])  # bare id, embedding not probed
            proposed = (vault / "AI" / "System" / "Provider-Registry-proposed.md").read_text(encoding="utf-8")
            row = [ln for ln in proposed.splitlines() if "gemini-2.5-flash" in ln][0]
            self.assertNotIn("models/", row)
            self.assertIn("| active |", row)
            self.assertIn("Probed 1.", msg)
            self.assertIn("active (probe OK): 1", msg)
            self.assertIn("specialized: 1", msg)

    def test_rows_match_on_models_prefix(self):
        discovered = {"google": {"models": ["models/gemini-2.5-flash"], "error": None}}
        existing = [SimpleNamespace(provider="google", model_id="gemini-2.5-flash")]
        rows = iter_discovered_rows(discovered, existing)
        self.assertEqual(rows[0].model_id, "gemini-2.5-flash")
        self.assertIs(rows[0].prev, existing[0])


if __name__ == "__main__":
    unittest.main()
