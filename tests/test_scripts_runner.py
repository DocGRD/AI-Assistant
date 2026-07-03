"""Tests for the M15 muscle-memory script runner (propose/commit guardrails)."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.scripts_runner import run_vault_script


class ScriptRunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "AI" / "Scripts" / "proposed").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_invalid_names_rejected(self):
        for bad in ("../x", "a/b", "a.b", "", "x;rm -rf"):
            ok, msg = run_vault_script(str(self.vault), bad)
            self.assertFalse(ok)
            self.assertIn("Invalid", msg)

    def test_missing_or_unapproved_script(self):
        # a proposed (not yet approved) script cannot be run
        (self.vault / "AI" / "Scripts" / "proposed" / "draft.py").write_text("print('x')", encoding="utf-8")
        ok, msg = run_vault_script(str(self.vault), "draft")
        self.assertFalse(ok)
        self.assertIn("No approved script", msg)

    def test_runs_approved_script(self):
        (self.vault / "AI" / "Scripts" / "hello.py").write_text("print('HI FROM SCRIPT')", encoding="utf-8")
        ok, out = run_vault_script(str(self.vault), "hello")
        self.assertTrue(ok, out)
        self.assertIn("HI FROM SCRIPT", out)

    def test_nonzero_exit_reported(self):
        (self.vault / "AI" / "Scripts" / "boom.py").write_text("import sys; sys.exit(2)", encoding="utf-8")
        ok, _ = run_vault_script(str(self.vault), "boom")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
