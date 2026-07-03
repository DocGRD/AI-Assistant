"""M28 — study reinforcement / spaced repetition. Stdlib unittest."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.study import cards as S


class ParseGenerateTests(unittest.TestCase):
    def test_parse_cards(self):
        c = S.parse_cards("Q: What is the last hour?\nA: The final era.\n\nQ: Who is antichrist?\nA: A deceiver.")
        self.assertEqual(len(c), 2)
        self.assertEqual(c[0]["q"], "What is the last hour?")
        self.assertEqual(S.parse_cards("NONE"), [])

    def test_generate_cards_forces_private(self):
        calls = {"private": None}
        class _R:
            def generate(self, messages, system_prompt="", private=False, **kw):
                calls["private"] = private
                return "Q: What genus?\nA: Sialia.", "groq"
        out = S.generate_cards(_R(), "Bluebirds are genus Sialia.")
        self.assertEqual(out, [{"q": "What genus?", "a": "Sialia."}])
        self.assertTrue(calls["private"])


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_dedupes(self):
        cards = [{"q": "a", "a": "1"}, {"q": "a", "a": "1"}, {"q": "b", "a": "2"}]
        self.assertEqual(S.add_cards(self.vault, cards, "Note.md", today="2026-07-02"), 2)
        self.assertEqual(len(S._load(self.vault)), 2)

    def test_sm2_progression_and_fail(self):
        card = S._new_card("q", "a", "n", "2026-07-02")
        S.sm2(card, 4, today="2026-07-02"); self.assertEqual(card["interval"], 1)   # rep 1
        S.sm2(card, 4, today="2026-07-02"); self.assertEqual(card["interval"], 6)   # rep 2
        S.sm2(card, 4, today="2026-07-02"); self.assertGreater(card["interval"], 6) # rep 3 = 6*ease
        S.sm2(card, 1, today="2026-07-02")                                          # fail → reset
        self.assertEqual(card["interval"], 1)
        self.assertEqual(card["reps"], 0)
        self.assertGreaterEqual(card["ease"], 1.3)

    def test_due_and_review(self):
        S.add_cards(self.vault, [{"q": "q", "a": "a"}], "n", today="2026-07-02")
        self.assertEqual(len(S.due_cards(self.vault, today="2026-07-02")), 1)   # due today
        cid = S._load(self.vault)[0]["id"]
        self.assertTrue(S.review(self.vault, cid, 5, today="2026-07-02"))       # pass → pushed out
        self.assertEqual(len(S.due_cards(self.vault, today="2026-07-02")), 0)   # not due today
        self.assertFalse(S.review(self.vault, "nope", 5))                       # unknown card


if __name__ == "__main__":
    unittest.main()
