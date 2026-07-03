"""GUI automation harness — oracle + fixture + report tests. Stdlib unittest.

These exercise the zero-cost ground-truth oracles against a seeded temp vault; no
server, no provider calls.
"""

import tempfile
import unittest
from pathlib import Path

from assistant_core.testing.gui_harness import GuiHarness, SCENARIOS, FIXTURE_DIR


class GuiHarnessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "AI" / "Help").mkdir(parents=True, exist_ok=True)
        for n in ("Commands.md", "Features.md", "Getting-Started.md"):
            (self.vault / "AI" / "Help" / n).write_text("# " + n, encoding="utf-8")
        # Genuine (non-test-folder) knowledge notes: provenance/passage exclude AI/Tests,
        # so the sourced/passage oracles must find real content outside it — exactly as
        # they do against the live vault.
        (self.vault / "Notes").mkdir(exist_ok=True)
        (self.vault / "Notes" / "heater.md").write_text(
            "A rocket mass heater stores thermal mass and burns wood cleanly.", encoding="utf-8")
        (self.vault / "Study").mkdir(exist_ok=True)
        (self.vault / "Study" / "1john.md").write_text(
            "Notes on 1 John 2:18-20 — the antichrist and the last hour.", encoding="utf-8")
        self.h = GuiHarness(settings={"vault_path": str(self.vault),
                                      "host": "127.0.0.1", "port": 8765})

    def tearDown(self):
        self._tmp.cleanup()

    def test_seed_writes_all_fixtures(self):
        written = self.h.seed_fixtures()
        self.assertTrue(all((self.vault / f).exists() for f in written))
        self.assertTrue((self.vault / FIXTURE_DIR / "gui-fixture-heater.md").exists())

    def test_oracles_pass_after_seeding(self):
        self.h.seed_fixtures()
        results = self.h.run_oracles()
        self.assertEqual(len(results), len(SCENARIOS))
        failures = [(s.id, r.detail) for s, r in results if not r.ok]
        self.assertEqual(failures, [], f"oracles failed: {failures}")

    def test_unsourced_oracle_is_negative(self):
        # The unsourced scenario must report *not* sourced even with fixtures present.
        self.h.seed_fixtures()
        unsourced = next(s for s in SCENARIOS if s.id == "GUI.04")
        self.assertTrue(unsourced.oracle(self.vault).ok)

    def test_report_renders_table_and_summary(self):
        self.h.seed_fixtures()
        md = self.h.render_report(self.h.run_oracles())
        self.assertIn("| ID | Milestone |", md)
        self.assertIn("Oracle summary:", md)
        for s in SCENARIOS:
            self.assertIn(s.id, md)

    def test_probe_payload_shape(self):
        # base_url is derived from settings; no network here.
        self.assertEqual(self.h.base_url, "http://127.0.0.1:8765")


if __name__ == "__main__":
    unittest.main()
