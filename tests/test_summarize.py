"""M45 — map-reduce summarization of oversized content (chunk → summarize → combine)."""

import unittest
from unittest import mock

from assistant_core.summarize import map_reduce_summarize


class _Router:
    """Fake summarizer: each chunk → a short line, echoing SECRET42 if the chunk contains it
    (so we can assert both shrinkage AND key-point retention)."""
    available_providers = ["groq"]

    def __init__(self):
        self.calls = 0

    def generate(self, messages, system_prompt="", task=None, private=False, allow_webui=True, **kw):
        self.calls += 1
        content = messages[0].content
        tag = "SECRET42" if "SECRET42" in content else f"c{self.calls}"
        return f"[summary:{tag}]", "groq"


class MapReduceTests(unittest.TestCase):
    def test_small_text_passes_through_unchanged(self):
        self.assertEqual(map_reduce_summarize("just a little text", _Router(), {}, target_chars=6000),
                         "just a little text")

    def test_condenses_big_text_and_retains_key_fact(self):
        text = ("This is a paragraph of filler content that repeats. " * 40 + "\n\n") * 30
        text += "\n\nSECRET42 is the one fact that must survive.\n\n"
        r = _Router()
        with mock.patch("assistant_core.local_llm.available", return_value=False):
            out = map_reduce_summarize(text, r, {}, target_chars=2000, focus="the key fact")
        self.assertLess(len(out), len(text))          # shrank
        self.assertLessEqual(len(out), 2000)          # fits the target
        self.assertIn("SECRET42", out)                # key point retained through map-reduce
        self.assertGreater(r.calls, 1)                # actually did per-chunk summaries

    def test_prefers_local_model_when_available(self):
        text = "big " * 8000                          # ~32k chars
        with mock.patch("assistant_core.local_llm.available", return_value=True), \
             mock.patch("assistant_core.local_llm.complete", return_value="LOCAL SUMMARY") as lc:
            out = map_reduce_summarize(text, _Router(), {}, target_chars=1000)
        self.assertLessEqual(len(out), 1000)
        self.assertTrue(lc.called)                    # used the local (free) model
        self.assertIn("LOCAL SUMMARY", out)

    def test_falls_back_to_truncation_without_any_summarizer(self):
        text = "word " * 20000                        # ~100k chars
        class _NoRouter:
            available_providers = []
        with mock.patch("assistant_core.local_llm.available", return_value=False):
            out = map_reduce_summarize(text, _NoRouter(), {}, target_chars=3000)
        self.assertLessEqual(len(out), 3000)          # still fits (degrades to truncation)
        self.assertIn("truncated", out)


if __name__ == "__main__":
    unittest.main()
