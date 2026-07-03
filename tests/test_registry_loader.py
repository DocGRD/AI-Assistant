"""
Tests for providers/registry_loader.py (Milestone 10, Slice 1).

Stdlib unittest only — no pytest dependency. Run with:
    python -m unittest tests.test_registry_loader -v

Covers:
  - load() parses well-formed rows into ModelSpec with the expected fields.
  - a deliberately broken row is skipped (and reported) without crashing.
  - a "?" limit maps to the NO_KNOWN_LIMIT sentinel.
  - a missing file returns [] rather than raising.
"""

import tempfile
import unittest
from pathlib import Path

from assistant_core.providers.registry_loader import RegistryLoader, NO_KNOWN_LIMIT

# Two valid rows (groq 70B, google) + one deliberately broken row
# (context_window = "abc" is not an int → the row must be skipped, not fatal).
SAMPLE_REGISTRY = """# Provider Registry

## Active Providers

| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | trains_on_data | status | strengths | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| groq | https://api.groq.com/openai/v1 | llama-3.3-70b-versatile | 128000 | 12000 | 30 | 1000 | 100000 | no | active | reasoning, tool-use, fast | tight daily cap |
| google | https://generativelanguage.googleapis.com/v1beta/openai/ | gemini-2.5-flash | 1000000 | 250000 | 15 | 1500 | ? | yes | active | long-context, multimodal | default |
| broken | https://example.com/v1 | bad-model | abc | 12000 | 30 | 1000 | 100000 | no | active | nonsense | this row has a non-integer context_window |

## Deprecated / Removed

| provider_key | model_id | removed_date | reason |
|---|---|---|---|
| groq | mixtral-8x7b-32768 | 2026-03-01 | Deprecated by Groq |
"""


class RegistryLoaderTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "Provider-Registry.md"
        self.path.write_text(SAMPLE_REGISTRY, encoding="utf-8")
        self.loader = RegistryLoader(self.path)
        self.specs = self.loader.load()

    def tearDown(self):
        self._tmp.cleanup()

    def _spec(self, provider, model_id):
        for s in self.specs:
            if s.provider == provider and s.model_id == model_id:
                return s
        return None

    def test_valid_rows_loaded(self):
        # Two good rows; the deprecated table (different schema) is ignored.
        self.assertEqual(len(self.specs), 2)

        groq = self._spec("groq", "llama-3.3-70b-versatile")
        self.assertIsNotNone(groq)
        self.assertEqual(groq.base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(groq.tpm_limit, 12000)
        self.assertEqual(groq.context_window, 128000)
        self.assertEqual(groq.status, "active")
        self.assertEqual(groq.trains_on_data, "no")
        self.assertIn("reasoning", groq.strengths)
        self.assertIn("tool-use", groq.strengths)

        google = self._spec("google", "gemini-2.5-flash")
        self.assertIsNotNone(google)
        self.assertEqual(
            google.base_url,
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.assertEqual(google.context_window, 1000000)

    def test_broken_row_skipped_and_reported(self):
        # The broken row must NOT be in the specs ...
        self.assertIsNone(self._spec("broken", "bad-model"))
        # ... and it must be reported, not silently dropped.
        self.assertEqual(len(self.loader.skipped), 1)
        self.assertIn("broken", self.loader.skipped[0])

    def test_unknown_limit_maps_to_sentinel(self):
        # google's tpd is "?" → treated as "no known limit".
        google = self._spec("google", "gemini-2.5-flash")
        self.assertEqual(google.tpd_limit, NO_KNOWN_LIMIT)

    def test_missing_file_returns_empty(self):
        loader = RegistryLoader(Path(self._tmp.name) / "does-not-exist.md")
        self.assertEqual(loader.load(), [])


if __name__ == "__main__":
    unittest.main()
