"""M16.7 — self-discovering registry proposer. Stdlib unittest."""

import unittest
from types import SimpleNamespace

from assistant_core.providers.registry_proposer import (
    is_chat_model, classify_strengths, classify_non_chat, build_proposed_registry,
)


def _spec(provider, mid, status="active", rpd_limit=1000, context_window=128000, notes="hand note"):
    return SimpleNamespace(provider=provider, model_id=mid, status=status,
                           rpd_limit=rpd_limit, context_window=context_window, notes=notes)


class IsChatModelTests(unittest.TestCase):
    def test_keeps_normal_chat(self):
        for good in ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "gemini-3.1-flash-lite"]:
            self.assertTrue(is_chat_model(good), good)

    def test_drops_non_chat(self):
        for bad in ["text-embedding-3-small", "whisper-large-v3", "llama-guard-4-12b",
                    "gemini-2.5-flash-image", "playai-tts", "rerank-v3"]:
            self.assertFalse(is_chat_model(bad), bad)


class ClassifyStrengthsTests(unittest.TestCase):
    def test_reasoning_and_fast(self):
        self.assertIn("reasoning", classify_strengths("openai/gpt-oss-120b"))
        self.assertIn("fast", classify_strengths("gemini-3.1-flash-lite"))

    def test_multimodal_and_default(self):
        self.assertIn("multimodal", classify_strengths("meta-llama/llama-4-scout-17b-16e-instruct"))
        self.assertEqual(classify_strengths("some-unknown-model"), ["general"])


class BuildProposedRegistryTests(unittest.TestCase):
    def test_filters_preserves_and_marks_candidates(self):
        discovered = {"groq": {"models": ["llama-3.3-70b-versatile", "whisper-large-v3",
                                          "openai/gpt-oss-20b"], "error": None}}
        existing = [_spec("groq", "llama-3.3-70b-versatile", status="active", notes="my note")]
        md = build_proposed_registry(discovered, existing, {"groq": "https://api.groq.com/openai/v1"})
        self.assertIn("llama-3.3-70b-versatile", md)
        self.assertIn("openai/gpt-oss-20b", md)           # new model included
        self.assertIn("my note", md)                      # existing note preserved
        self.assertIn("| active |", md)                   # existing status preserved
        self.assertIn("| candidate |", md)                # new model is candidate

    def test_non_chat_models_kept_in_second_table(self):
        discovered = {"groq": {"models": ["llama-3.3-70b-versatile", "whisper-large-v3",
                                          "text-embedding-3-small"], "error": None}}
        md = build_proposed_registry(discovered, [], {"groq": "https://x"})
        self.assertIn("Specialized / non-chat", md)       # second table exists
        self.assertIn("whisper-large-v3", md)             # NOT dropped anymore
        self.assertIn("text-embedding-3-small", md)
        self.assertIn("transcription", md)                # whisper categorised
        self.assertIn("embedding", md)                    # embed categorised

    def test_classify_non_chat_categories(self):
        self.assertEqual(classify_non_chat("whisper-large-v3"), "transcription")
        self.assertEqual(classify_non_chat("text-embedding-3-small"), "embedding")
        self.assertEqual(classify_non_chat("llama-guard-4-12b"), "safety")
        self.assertEqual(classify_non_chat("playai-tts"), "text-to-speech")

    def test_skips_provider_with_error(self):
        discovered = {"bad": {"models": [], "error": "401 unauthorized"}}
        md = build_proposed_registry(discovered, [], {"bad": "https://x"})
        self.assertNotIn("https://x", md)                 # errored provider contributes no rows


if __name__ == "__main__":
    unittest.main()
