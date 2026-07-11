"""GUI-plan T02.2 — Vault QA must not attach source chips to a refusal ("I don't know")."""

import unittest


class QaRefusalTests(unittest.TestCase):
    def _fn(self):
        from assistant_core.server.core import _is_qa_refusal
        return _is_qa_refusal

    def test_refusals_detected(self):
        f = self._fn()
        for a in ("I don't know.", "I do not know the answer.",
                  "No relevant information was found in the vault.",
                  "I can't find that in your notes.", "I cannot answer that from the vault.",
                  "Not enough information to answer.",
                  "The vault doesn't contain anything about that.",
                  "There is no mention of Atlantis's GDP."):
            self.assertTrue(f(a), a)

    def test_real_answers_not_flagged(self):
        f = self._fn()
        for a in ("Bluebirds nest in cavities and belong to genus Sialia.",
                  "According to your notes, the meeting is on Tuesday.",
                  "The answer is 42, per Aethel Money.md.",
                  "I know this one: fellowship with the Father."):  # 'I know' must NOT match
            self.assertFalse(f(a), a)


if __name__ == "__main__":
    unittest.main()
