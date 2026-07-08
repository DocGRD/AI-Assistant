"""M38 — Map-of-Content generation (propose-only, validated links)."""

import tempfile
import unittest
from pathlib import Path

from assistant_core import moc


class MocTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        (v / "Rocket Stove.md").write_text("A rocket stove burns wood efficiently.", encoding="utf-8")
        (v / "Rocket Mass Heater.md").write_text("A rocket mass heater stores rocket stove heat.", encoding="utf-8")
        (v / "Gardening.md").write_text("Tomatoes need sun.", encoding="utf-8")

    def test_builds_propose_only_moc(self):
        rel = moc.build_moc(self.tmp, "rocket stove")
        self.assertTrue(rel.startswith("AI/Proposed/moc-"))
        txt = (Path(self.tmp) / rel).read_text(encoding="utf-8")
        self.assertIn("[[Rocket Stove]]", txt)
        self.assertIn("[[Rocket Mass Heater]]", txt)
        self.assertNotIn("[[Gardening]]", txt)          # unrelated → excluded
        # source notes untouched
        self.assertNotIn("MOC", (Path(self.tmp) / "Rocket Stove.md").read_text(encoding="utf-8"))

    def test_none_when_no_matches(self):
        self.assertIsNone(moc.build_moc(self.tmp, "quantum chromodynamics"))

    def test_links_validated(self):
        rel = moc.build_moc(self.tmp, "rocket")
        txt = (Path(self.tmp) / rel).read_text(encoding="utf-8")
        for line in txt.splitlines():
            if line.startswith("- [["):
                stem = line[4:].split("]]")[0]
                self.assertTrue((Path(self.tmp) / f"{stem}.md").exists())


if __name__ == "__main__":
    unittest.main()
