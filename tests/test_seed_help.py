"""v1.7 — self-updating AI/Help knowledge base (packaged seed, version-stamped)."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.memory.memory_manager import MemoryManager, HELP_VERSION


class SeedHelpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mm = MemoryManager(self.tmp)

    def test_seeds_when_missing(self):
        written = self.mm.seed_help()
        self.assertTrue(written)
        self.assertIn("AI/Help/How-To-Use.md", written)
        c = Path(self.tmp) / "AI" / "Help" / "Commands.md"
        self.assertTrue(c.exists())
        self.assertIn("Command Reference", c.read_text(encoding="utf-8"))
        self.assertIn(f"help-version: {HELP_VERSION}", c.read_text(encoding="utf-8"))

    def test_idempotent_when_current(self):
        self.mm.seed_help()
        self.assertEqual(self.mm.seed_help(), [])       # nothing rewritten the second time

    def test_refreshes_when_stale(self):
        self.mm.seed_help()
        p = Path(self.tmp) / "AI" / "Help" / "Commands.md"
        p.write_text("<!-- help-version: 1 -->\nold stale content", encoding="utf-8")  # simulate old copy
        written = self.mm.seed_help()
        self.assertIn("AI/Help/Commands.md", written)
        self.assertIn("Command Reference", p.read_text(encoding="utf-8"))   # refreshed to current

    def test_force_rewrites_all(self):
        self.mm.seed_help()
        self.assertTrue(self.mm.seed_help(force=True))   # force rewrites even when current

    def test_help_notes_are_indexable(self):
        # AI/Help is NOT in the RAG exclude list → it can be questioned
        from assistant_core.rag.indexer import DEFAULT_EXCLUDES
        self.assertFalse(any(e.startswith("AI/Help") for e in DEFAULT_EXCLUDES))


if __name__ == "__main__":
    unittest.main()
