"""
Tests for live model discovery (vault:models) — the parsing/error handling, with
an injected list_fn so nothing hits the network.
"""

import unittest

from assistant_core.providers.model_discovery import discover_models


class DiscoverModelsTests(unittest.TestCase):
    def test_lists_per_provider_and_handles_errors(self):
        providers = {"groq": "u1", "google": "u2", "nokey": "u3"}
        config = {"groq_api_key": "k1", "google_api_key": "k2"}   # nokey has no key

        def fake(base_url, key):
            if base_url == "u1":
                return ["b", "a"]            # returned as-is (caller already sorts upstream)
            raise RuntimeError("boom 404")

        with self.assertLogs("assistant", level="WARNING"):   # google 'boom 404' is expected
            res = discover_models(providers, config, list_fn=fake)
        self.assertEqual(res["groq"], {"models": ["b", "a"], "error": None})
        self.assertEqual(res["google"]["models"], [])
        self.assertIn("boom 404", res["google"]["error"])
        self.assertEqual(res["nokey"]["error"], "no api key set")

    def test_empty_providers(self):
        self.assertEqual(discover_models({}, {}, list_fn=lambda b, k: []), {})


if __name__ == "__main__":
    unittest.main()
