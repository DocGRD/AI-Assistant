"""M26 — structured & exact search. Stdlib unittest."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.query import structured_search


class StructuredSearchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        self._note("Sermons/Antichrist.md",
                   "---\ntags: [sermon]\nproject: preaching\n---\n"
                   "The ESV renders the antichrist warning in the last hour. #study")
        self._note("06 - Projects/Camping.md",
                   "---\nproject: camping\n---\nGear list and tarps. #outdoors")
        self._note("AI/Memory/Episodes/2026-07-02.md", "sermon ESV antichrist logged query")

    def tearDown(self):
        self._tmp.cleanup()

    def _note(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def _paths(self, q):
        return {r["path"] for r in structured_search(self.vault, q)}

    def test_tag(self):
        self.assertEqual(self._paths("tag:sermon"), {"Sermons/Antichrist.md"})
        self.assertIn("Sermons/Antichrist.md", self._paths("tag:study"))   # inline #study

    def test_path(self):
        self.assertEqual(self._paths('path:"06 - Projects"'), {"06 - Projects/Camping.md"})

    def test_frontmatter_field(self):
        self.assertEqual(self._paths("fm:project=camping"), {"06 - Projects/Camping.md"})

    def test_phrase_and_words(self):
        self.assertIn("Sermons/Antichrist.md", self._paths('"the last hour"'))
        self.assertEqual(self._paths("gear tarps"), {"06 - Projects/Camping.md"})   # all-words

    def test_near(self):
        self.assertIn("Sermons/Antichrist.md", self._paths("ESV NEAR/3 antichrist"))
        self.assertEqual(self._paths("ESV NEAR/1 antichrist"), set())   # too far apart

    def test_combined_predicates(self):
        self.assertEqual(self._paths("tag:sermon ESV"), {"Sermons/Antichrist.md"})

    def test_episodes_excluded(self):
        self.assertNotIn("AI/Memory/Episodes/2026-07-02.md", self._paths("ESV antichrist"))


if __name__ == "__main__":
    unittest.main()
