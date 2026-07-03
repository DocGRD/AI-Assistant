"""M24 — scripture reference parsing + passage guide. Stdlib unittest."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.scripture.refs import parse_refs, refs_overlap, parse_refs_struct, normalize_ref
from assistant_core.scripture.passage import find_passage_notes, build_passage_guide


class ParseRefsTests(unittest.TestCase):
    def test_common_forms(self):
        self.assertEqual(parse_refs("see 1 Jn 2:18 today"), ["1 John 2:18"])
        self.assertEqual(parse_refs("1 John 2:18-20"), ["1 John 2:18-20"])
        self.assertEqual(parse_refs("John 3:16"), ["John 3:16"])
        self.assertEqual(parse_refs("Ps 23:1"), ["Psalms 23:1"])
        self.assertEqual(parse_refs("Rom 8:28 and Gal 5:22"), ["Romans 8:28", "Galatians 5:22"])

    def test_dedupe_and_nonrefs(self):
        self.assertEqual(parse_refs("John 3:16 ... John 3:16"), ["John 3:16"])
        self.assertEqual(parse_refs("meeting at 2:30 about page 4:5 stuff"), [])
        self.assertEqual(parse_refs("no references here"), [])

    def test_normalize_and_overlap(self):
        self.assertEqual(normalize_ref("1 jn 2:18-20"), "1 John 2:18-20")
        a = parse_refs_struct("1 John 2:18-27")[0]
        b = parse_refs_struct("1 John 2:18-20")[0]
        self.assertTrue(refs_overlap(a, b))
        c = parse_refs_struct("1 John 3:1")[0]
        self.assertFalse(refs_overlap(a, c))          # different chapter


class PassageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _note(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_find_passage_notes_overlap(self):
        self._note("Sermons/Antichrist.md", "Preached on 1 John 2:18-27 about the last hour.")
        self._note("Study/Verse.md", "1 John 2:19 — they went out from us.")
        self._note("Other/Unrelated.md", "About John 3:16 instead.")
        self._note("AI/System/skip.md", "1 John 2:18 should be skipped (derived tree)")
        hits = find_passage_notes(self.vault, "1 John 2:18-20")
        paths = {h["path"] for h in hits}
        self.assertIn("Sermons/Antichrist.md", paths)     # range overlap
        self.assertIn("Study/Verse.md", paths)            # single verse inside range
        self.assertNotIn("Other/Unrelated.md", paths)     # different passage
        self.assertNotIn("AI/System/skip.md", paths)      # derived tree skipped

    def test_build_passage_guide(self):
        self._note("Sermons/Antichrist.md", "1 John 2:18-20: antichrists and the anointing.")
        class _R:
            def generate(self, messages, system_prompt="", **kw):
                return "The passage warns of antichrists [[Antichrist]].", "groq"
        rep = build_passage_guide(self.vault, _R(), "1 John 2:18")
        self.assertEqual(rep["ref"], "1 John 2:18")
        self.assertIn("antichrists", rep["guide"])
        self.assertIn("Sermons/Antichrist.md", rep["notes"])

    def test_bad_ref_and_no_notes(self):
        self.assertIn("not a recognised", build_passage_guide(self.vault, None, "not a ref")["error"])
        self.assertIn("no notes", build_passage_guide(self.vault, None, "Jude 1:3")["error"])


if __name__ == "__main__":
    unittest.main()
