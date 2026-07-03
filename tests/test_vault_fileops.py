"""M16.6 — vault file ops (copy/move/trash/mkdir) + path jail. Stdlib unittest."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.paths import resolve_in_vault
from assistant_core.tools.file_ops import (
    CopyPathTool, MovePathTool, TrashPathTool, MkdirTool,
)


class PathJailTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_resolves_descendant(self):
        p = resolve_in_vault(self.vault, "06 - Projects/Tech/a.md")
        self.assertTrue(str(p).startswith(str(self.vault.resolve())))

    def test_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            resolve_in_vault(self.vault, "../outside.md")

    def test_rejects_absolute(self):
        with self.assertRaises(ValueError):
            resolve_in_vault(self.vault, "C:/Windows/system32")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            resolve_in_vault(self.vault, "   ")


class FileOpsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        for rel in ["06 - Projects/Tech/a.md", "06 - Projects/Tech/sub/b.md",
                    "06 - Projects/c.md"]:
            p = self.vault / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
        v = str(self.vault)
        self.copy, self.move = CopyPathTool(v), MovePathTool(v)
        self.trash, self.mkdir = TrashPathTool(v), MkdirTool(v)

    def tearDown(self):
        self._tmp.cleanup()

    def test_copy_folder_tree(self):
        r = self.copy.run("06 - Projects/Tech -> 06 - Projects/Tech-backup")
        self.assertTrue(r.success, r.output)
        self.assertEqual(r.metadata["notes"], 2)                      # a + nested b
        self.assertTrue((self.vault / "06 - Projects/Tech-backup/sub/b.md").exists())
        self.assertTrue((self.vault / "06 - Projects/Tech/a.md").exists())  # original kept

    def test_copy_rejects_existing_dst(self):
        self.assertFalse(self.copy.run("06 - Projects/c.md -> 06 - Projects/Tech/a.md").success)

    def test_copy_needs_separator(self):
        self.assertFalse(self.copy.run("06 - Projects/c.md").success)

    def test_move_renames(self):
        r = self.move.run("06 - Projects/c.md -> 06 - Projects/renamed.md")
        self.assertTrue(r.success, r.output)
        self.assertFalse((self.vault / "06 - Projects/c.md").exists())
        self.assertTrue((self.vault / "06 - Projects/renamed.md").exists())

    def test_trash_is_recoverable(self):
        r = self.trash.run("06 - Projects/c.md")
        self.assertTrue(r.success, r.output)
        self.assertFalse((self.vault / "06 - Projects/c.md").exists())
        self.assertTrue((self.vault / ".trash/06 - Projects/c.md").exists())

    def test_trash_disambiguates_collision(self):
        self.trash.run("06 - Projects/c.md")
        (self.vault / "06 - Projects/c.md").write_text("y", encoding="utf-8")
        r = self.trash.run("06 - Projects/c.md")                      # second trash of same path
        self.assertTrue(r.success, r.output)
        trashed = sorted((self.vault / ".trash/06 - Projects").glob("c*.md"))
        self.assertEqual(len(trashed), 2)                             # both preserved

    def test_mkdir_creates_parents(self):
        r = self.mkdir.run("06 - Projects/New/Deep")
        self.assertTrue(r.success, r.output)
        self.assertTrue((self.vault / "06 - Projects/New/Deep").is_dir())

    def test_ops_reject_escape(self):
        self.assertFalse(self.move.run("../x.md -> ../y.md").success)
        self.assertFalse(self.trash.run("../../etc/passwd").success)
        self.assertFalse(self.mkdir.run("../escape").success)


if __name__ == "__main__":
    unittest.main()
