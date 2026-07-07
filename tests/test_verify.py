"""M30 — hallucination guard (guard_answer): grounded / escalate / web-verify / flag."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.verify import guard_answer


class FakeRouter:
    """Router whose escalation reply is configurable."""
    def __init__(self, reply="escalated answer about widgets"):
        self._reply = reply
        self.calls = 0

    def generate(self, messages, **kw):
        self.calls += 1
        return self._reply, "big-model"


def _search_hits(_q, _k):
    return [
        {"title": "Widget Facts", "url": "https://example.com/widgets", "snippet": "..."},
        {"title": "More Widgets", "url": "https://example.org/w", "snippet": "..."},
    ]


def _no_hits(_q, _k):
    return []


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # A note that supports a claim about "photosynthesis chlorophyll sunlight".
        (Path(self.tmp) / "Bio.md").write_text(
            "Photosynthesis uses chlorophyll to convert sunlight into energy.",
            encoding="utf-8")
        self.cfg = {"vault_path": self.tmp, "hallucination_guard": "escalate_web",
                    "web_research_enabled": True}
        self.router = FakeRouter()

    def test_grounded_answer_passes_through(self):
        ans = "Photosynthesis uses chlorophyll and sunlight."
        out, status = guard_answer(ans, "how does photosynthesis work",
                                   self.router, self.tmp, self.cfg, search_fn=_search_hits)
        self.assertEqual(status, "grounded")
        self.assertEqual(out, ans)
        self.assertEqual(self.router.calls, 0)          # no escalation needed

    def test_ungrounded_escalates_then_web_verifies(self):
        # A claim with no vault support; escalation also ungrounded → web citations attached.
        out, status = guard_answer("The Zorblax device runs on flurbium cells.",
                                   "what powers the Zorblax device",
                                   self.router, self.tmp, self.cfg, search_fn=_search_hits)
        self.assertEqual(status, "web_verified")
        self.assertIn("Sources (web-verified):", out)
        self.assertIn("https://example.com/widgets", out)
        self.assertGreaterEqual(self.router.calls, 1)   # escalation attempted

    def test_ungrounded_no_web_flags(self):
        out, status = guard_answer("The Zorblax device runs on flurbium cells.",
                                   "what powers the Zorblax device",
                                   self.router, self.tmp, self.cfg, search_fn=_no_hits)
        self.assertEqual(status, "unverified")
        self.assertIn("⚠", out)
        self.assertIn("Unverified", out)

    def test_private_never_web_verifies(self):
        # Private content: even if ungrounded, no escalation/web — just a flag.
        out, status = guard_answer("Secret plan uses the Zorblax device.",
                                   "what is the secret plan",
                                   self.router, self.tmp, self.cfg,
                                   private=True, search_fn=_search_hits)
        self.assertEqual(status, "flagged_private")
        self.assertIn("⚠", out)
        self.assertEqual(self.router.calls, 0)          # no model/web calls for private

    def test_policy_off_is_noop(self):
        cfg = dict(self.cfg, hallucination_guard="off")
        ans = "anything at all"
        out, status = guard_answer(ans, "q", self.router, self.tmp, cfg, search_fn=_search_hits)
        self.assertEqual(status, "off")
        self.assertEqual(out, ans)

    def test_policy_flag_only(self):
        cfg = dict(self.cfg, hallucination_guard="flag")
        out, status = guard_answer("The Zorblax device runs on flurbium.", "q",
                                   self.router, self.tmp, cfg, search_fn=_search_hits)
        self.assertEqual(status, "flagged")
        self.assertIn("⚠", out)
        self.assertEqual(self.router.calls, 0)          # flag policy skips escalation


if __name__ == "__main__":
    unittest.main()
