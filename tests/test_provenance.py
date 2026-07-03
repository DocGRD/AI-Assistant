"""M25 — provenance / source audit. Stdlib unittest."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.provenance import find_sources, _terms


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "Notes").mkdir(parents=True, exist_ok=True)
        (self.vault / "Notes" / "Heater.md").write_text(
            "Rocket mass heaters store thermal mass and burn wood cleanly.", encoding="utf-8")
        (self.vault / "Notes" / "Camping.md").write_text("Tarps and gear for camping trips.", encoding="utf-8")
        (self.vault / "AI" / "Memory" / "Episodes").mkdir(parents=True, exist_ok=True)
        (self.vault / "AI" / "Memory" / "Episodes" / "2026-07-02.md").write_text(
            "rocket mass heaters thermal wood", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_terms_drops_stopwords_and_short(self):
        self.assertNotIn("this", _terms("this rocket heater"))
        self.assertIn("rocket", _terms("this rocket heater"))

    def test_finds_supporting_note(self):
        r = find_sources(self.vault, "rocket mass heaters store thermal mass")
        self.assertTrue(r["sourced"])
        self.assertEqual(r["sources"][0]["path"], "Notes/Heater.md")   # best match first

    def test_unsourced_claim(self):
        r = find_sources(self.vault, "quantum entanglement teleportation protocol")
        self.assertFalse(r["sourced"])

    def test_episodes_excluded(self):
        r = find_sources(self.vault, "rocket mass heaters thermal wood")
        paths = {s["path"] for s in r["sources"]}
        self.assertNotIn("AI/Memory/Episodes/2026-07-02.md", paths)


if __name__ == "__main__":
    unittest.main()
