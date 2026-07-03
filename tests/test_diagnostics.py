"""
Tests for vault-path validation (T3.20).

A path is a vault only if it exists, is a directory, AND contains `.obsidian/`.
This stops the assistant seeding the AI/ structure into a typo'd or non-vault
directory and disables the tools instead.
"""

import tempfile
import unittest
from pathlib import Path

from assistant_core.diagnostics import is_vault


class IsVaultTests(unittest.TestCase):
    def test_empty_or_missing_path(self):
        self.assertFalse(is_vault(""))
        self.assertFalse(is_vault("C:/definitely/not/here/xyz123"))

    def test_existing_dir_without_obsidian_is_not_a_vault(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(is_vault(d))          # exists but no .obsidian/ → not a vault

    def test_file_is_not_a_vault(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "note.md"
            f.write_text("hi", encoding="utf-8")
            self.assertFalse(is_vault(str(f)))

    def test_dir_with_obsidian_is_a_vault(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".obsidian").mkdir()
            self.assertTrue(is_vault(d))


if __name__ == "__main__":
    unittest.main()
