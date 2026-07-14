"""M37 — deterministic contradiction detection across the vault."""

import tempfile
import unittest
from pathlib import Path

from assistant_core import contradiction


class ContradictionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _w(self, name, text):
        (Path(self.tmp) / name).write_text(text, encoding="utf-8")

    def test_detects_quantity_conflict(self):
        self._w("a.md", "The annual conference attendance reached 5000 registered members.")
        self._w("b.md", "The annual conference attendance reached 8000 registered members.")
        pairs = contradiction.detect(self.tmp)
        self.assertTrue(pairs)
        self.assertEqual(pairs[0]["reason"], "quantity")
        notes = {pairs[0]["a"]["note"], pairs[0]["b"]["note"]}
        self.assertEqual(notes, {"a.md", "b.md"})

    def test_same_note_not_flagged_against_itself(self):
        # Two different sentences in ONE note must not be reported as a contradiction (this was
        # the "X vs X" briefing noise from the buggy `A or B and C` precedence).
        self._w("quotes.md",
                "The annual conference attendance reached 5000 registered members.\n\n"
                "The annual conference attendance reached 8000 registered members.")
        self.assertEqual(contradiction.detect(self.tmp), [])

    def test_no_conflict_when_subjects_differ(self):
        self._w("a.md", "The morning workshop had 5000 eager participants attending.")
        self._w("b.md", "The evening banquet served 8000 delicious gourmet dinner plates.")
        self.assertEqual(contradiction.detect(self.tmp), [])

    def test_same_numbers_no_conflict(self):
        self._w("a.md", "The annual conference attendance reached 5000 registered members.")
        self._w("b.md", "The annual conference attendance reached 5000 registered members total.")
        self.assertEqual(contradiction.detect(self.tmp), [])

    def test_render_empty(self):
        self.assertIn("No contradictions", contradiction.render_report([]))

    def test_confirm_pair_without_router(self):
        self.assertIsNone(contradiction.confirm_pair(None, {"a": {"text": "x"}, "b": {"text": "y"}}))


if __name__ == "__main__":
    unittest.main()
