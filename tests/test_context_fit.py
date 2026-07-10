"""v1.9.6 — router fits history to the provider it's actually sending to (per-attempt),
instead of the server pre-shrinking every request to the smallest provider."""

import unittest

from assistant_core.providers.provider_router import ProviderRouter


class _Spec:
    def __init__(self, tpm=0, ctx=0, provider="groq"):
        self.tpm_limit = tpm
        self.context_window = ctx
        self.provider = provider


class _Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class TestContextFit(unittest.TestCase):
    def test_input_budget_is_lower_of_tpm_and_window(self):
        # min(0.85 * tpm, ctx - response_reserve)
        self.assertEqual(ProviderRouter._input_budget(_Spec(tpm=6000, ctx=128000), 2048),
                         min(int(6000 * 0.85), 128000 - 2048))
        self.assertEqual(ProviderRouter._input_budget(_Spec(tpm=0, ctx=8192), 2048), 8192 - 2048)
        self.assertIsNone(ProviderRouter._input_budget(_Spec(provider="webui"), 2048))
        self.assertIsNone(ProviderRouter._input_budget(None, 2048))

    def test_big_window_provider_keeps_full_history(self):
        r = ProviderRouter.__new__(ProviderRouter)              # no __init__ needed for this helper
        msgs = [_Msg("user", "a " * 500), _Msg("assistant", "b " * 500), _Msg("user", "now")]
        fitted = r._fit_to_provider(msgs, _Spec(tpm=100000, ctx=128000), "sys", 2048)
        self.assertEqual(fitted, msgs)                          # roomy provider → nothing dropped

    def test_small_provider_drops_oldest_keeps_latest(self):
        r = ProviderRouter.__new__(ProviderRouter)
        msgs = [_Msg("user", "old " * 4000),                    # ~4k tokens, oldest
                _Msg("assistant", "mid " * 4000),
                _Msg("user", "the current question")]
        fitted = r._fit_to_provider(msgs, _Spec(tpm=6000, ctx=8192), "sys", 2048)
        self.assertLess(len(fitted), len(msgs))                # something was dropped
        self.assertEqual(fitted[-1].content, "the current question")  # latest message preserved


if __name__ == "__main__":
    unittest.main()
