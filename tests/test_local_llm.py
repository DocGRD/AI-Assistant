"""v1.9.7 — local small-model helper (Ollama) used for reductive summarisation only."""

import io
import json
import unittest
from unittest import mock

from assistant_core import local_llm


def _reset_cache():
    local_llm._avail_cache.update(checked=0.0, ok=False)
    local_llm._cooldown_until = 0.0


class TestLocalLLM(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def test_available_false_when_unreachable(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            self.assertFalse(local_llm.available({}, force=True))

    def test_available_true_when_ollama_answers(self):
        resp = mock.MagicMock(); resp.status = 200
        resp.__enter__ = lambda s: resp; resp.__exit__ = lambda *a: False
        with mock.patch("urllib.request.urlopen", return_value=resp):
            self.assertTrue(local_llm.available({}, force=True))

    def test_available_off_switch(self):
        self.assertFalse(local_llm.available({"local_model": "off"}, force=True))

    def test_complete_parses_openai_response(self):
        payload = {"choices": [{"message": {"content": "  a tidy summary  "}}]}
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = lambda s: resp; resp.__exit__ = lambda *a: False
        with mock.patch("urllib.request.urlopen", return_value=resp):
            out = local_llm.complete("text", "sys", {})
        self.assertEqual(out, "a tidy summary")

    def test_complete_none_on_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            self.assertIsNone(local_llm.complete("t", "s", {}))

    def test_failure_opens_cooldown_so_next_calls_fail_fast(self):
        # A timeout must NOT be paid again on every subsequent call in the same request
        # (this is what made a map-reduce hang N × timeout on a contended box).
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            self.assertIsNone(local_llm.complete("t", "s", {}))
        self.assertGreater(local_llm._cooldown_until, 0.0)
        # available() now short-circuits to False without touching the socket…
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("must not probe")):
            self.assertFalse(local_llm.available({}))
        # …until the cooldown expires.
        local_llm._cooldown_until = 0.0
        resp = mock.MagicMock(); resp.status = 200
        resp.__enter__ = lambda s: resp; resp.__exit__ = lambda *a: False
        with mock.patch("urllib.request.urlopen", return_value=resp):
            self.assertTrue(local_llm.available({}, force=True))

    def test_model_name_default_and_override(self):
        self.assertEqual(local_llm.model_name({}), local_llm.DEFAULT_MODEL)
        self.assertEqual(local_llm.model_name({"local_model": "gemma2:2b"}), "gemma2:2b")


class TestContextManagerUsesLocal(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def test_summarize_prefers_local_over_router(self):
        from assistant_core.memory.context_manager import ContextManager
        from assistant_core.providers.base_provider import Message

        router = mock.MagicMock()  # must NOT be called when local is available
        cm = ContextManager(mock.MagicMock(), router=router, config={})
        span = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
        with mock.patch.object(local_llm, "available", return_value=True), \
             mock.patch.object(local_llm, "summarize", return_value="LOCAL SUMMARY") as ls:
            out = cm._summarize(span, private=False)
        self.assertEqual(out, "LOCAL SUMMARY")
        ls.assert_called_once()
        router.generate.assert_not_called()

    def test_summarize_skips_cloud_when_not_opted_in(self):
        from assistant_core.memory.context_manager import ContextManager
        from assistant_core.providers.base_provider import Message

        router = mock.MagicMock()
        cm = ContextManager(mock.MagicMock(), router=router, config={})  # cloud_summarization off
        span = [Message(role="user", content="hi")]
        with mock.patch.object(local_llm, "available", return_value=False):
            out = cm._summarize(span, private=False)
        self.assertEqual(out, "")                 # → caller just trims
        router.generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
