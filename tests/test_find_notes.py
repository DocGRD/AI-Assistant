"""M16.6 — vault:find (glob enumeration, no 200-cap). Stdlib unittest."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.tools.find_notes import FindNotesTool


class FindNotesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        for rel in ["06 - Projects/Tech/a.md", "06 - Projects/Tech/sub/b.md",
                    "06 - Projects/Camping/c.md", "01 - God/d.md"]:
            p = self.vault / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
        self.tool = FindNotesTool(str(self.vault))

    def tearDown(self):
        self._tmp.cleanup()

    def test_glob_recurses(self):
        r = self.tool.run("06 - Projects/**/*.md")
        self.assertTrue(r.success)
        self.assertEqual(r.metadata["count"], 3)              # a, b (nested), c — not 01 - God
        self.assertIn("06 - Projects/Tech/sub/b.md", r.output)

    def test_bare_folder_expands_to_recursive(self):
        r = self.tool.run("06 - Projects")
        self.assertEqual(r.metadata["count"], 3)              # treated as 06 - Projects/**/*.md

    def test_no_match(self):
        r = self.tool.run("nope/**/*.md")
        self.assertTrue(r.success)
        self.assertEqual(r.metadata["count"], 0)

    def test_empty_is_usage_error(self):
        self.assertFalse(self.tool.run("  ").success)


if __name__ == "__main__":
    unittest.main()
