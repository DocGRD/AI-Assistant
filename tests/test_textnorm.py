"""Exotic-Unicode normalization (episodes/consolidation source-data hygiene)."""

import unittest

from assistant_core.textnorm import normalize_exotic, has_exotic


class TextNormTests(unittest.TestCase):
    def test_narrow_nbsp_and_nbsp_to_space(self):
        self.assertEqual(normalize_exotic("1" + chr(0x202f) + "John" + chr(0x202f) + "4"), "1 John 4")
        self.assertEqual(normalize_exotic("A" + chr(0x00a0) + "B"), "A B")

    def test_nonbreaking_hyphen_to_hyphen(self):
        self.assertEqual(normalize_exotic("1:1" + chr(0x2011) + "4"), "1:1-4")
        self.assertEqual(normalize_exotic("Re" + chr(0x2010) + "written"), "Re-written")

    def test_zero_width_removed(self):
        self.assertEqual(normalize_exotic("a" + chr(0x200b) + "b" + chr(0x2060) + "c"), "abc")
        self.assertEqual(normalize_exotic(chr(0xfeff) + "start"), "start")

    def test_preserves_real_punctuation_and_whitespace(self):
        # en/em dashes and ordinary spacing/newlines are intentional — keep them
        s = "Real — em dash, en – dash.\n\n  indented  spacing\ttab"
        self.assertEqual(normalize_exotic(s), s)

    def test_empty_and_plain(self):
        self.assertEqual(normalize_exotic(""), "")
        self.assertEqual(normalize_exotic("plain ascii text"), "plain ascii text")

    def test_has_exotic(self):
        self.assertTrue(has_exotic("1" + chr(0x202f) + "John"))
        self.assertTrue(has_exotic("a" + chr(0x200b)))
        self.assertFalse(has_exotic("plain — text with em dash"))

    def test_memory_write_normalizes(self):
        # the episode write funnel must strip exotic chars (source data for consolidation)
        import tempfile
        from pathlib import Path
        from assistant_core.memory.memory_manager import MemoryManager
        v = Path(tempfile.mkdtemp())
        (v / "AI" / "System").mkdir(parents=True, exist_ok=True)
        mm = MemoryManager(str(v))
        mm.open_episode()
        self.assertIsNotNone(mm._ep_path)
        mm.append_episode("You asked about 1" + chr(0x202f) + "John" + chr(0x202f) + "4 ESV")
        txt = Path(mm._ep_path).read_text(encoding="utf-8")
        self.assertIn("1 John 4 ESV", txt)
        self.assertNotIn(chr(0x202f), txt)


if __name__ == "__main__":
    unittest.main()
