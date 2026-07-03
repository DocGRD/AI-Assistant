"""Tests for MemoryManager.seed_prompts (M13 prompt library). Stdlib unittest."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.memory.memory_manager import MemoryManager


class SeedPromptsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.mm = MemoryManager(self._tmp.name)
        self.dir = Path(self._tmp.name) / "AI" / "Prompts"

    def tearDown(self):
        self._tmp.cleanup()

    def test_seeds_examples_when_empty(self):
        self.mm.seed_prompts()
        names = sorted(p.name for p in self.dir.glob("*.md"))
        self.assertIn("summarize.md", names)
        self.assertGreaterEqual(len(names), 3)
        self.assertIn("{{selection}}", (self.dir / "summarize.md").read_text(encoding="utf-8"))

    def test_does_not_clobber_existing(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "mine.md").write_text("custom", encoding="utf-8")
        self.mm.seed_prompts()                       # folder non-empty → no-op
        self.assertEqual((self.dir / "mine.md").read_text(encoding="utf-8"), "custom")
        self.assertFalse((self.dir / "summarize.md").exists())


if __name__ == "__main__":
    unittest.main()
