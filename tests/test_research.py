"""M5 — research workflow tools (research / import / summarise). Stdlib unittest, no network."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.tools.research_prompt import ResearchPromptTool
from assistant_core.tools.import_research import ImportResearchTool
from assistant_core.tools.summarise_research import SummariseResearchTool


class ResearchToolsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_research_prompt_generated(self):           # vault:research
        r = ResearchPromptTool(self.vault).run("clean combustion in rocket stoves")
        self.assertTrue(r.success)
        self.assertIn("combustion", r.output.lower())

    def test_research_prompt_empty_is_error(self):
        self.assertFalse(ResearchPromptTool(self.vault).run("   ").success)

    def test_import_creates_research_note(self):        # vault:import
        r = ImportResearchTool(self.vault).run("# Rocket Stove Findings\n\nThe riser height matters most.")
        self.assertTrue(r.success)
        path = Path(self.vault) / r.metadata["path"]
        self.assertTrue(path.exists() and path.parent.name == "Research")
        self.assertIn("riser height matters", path.read_text(encoding="utf-8"))

    def test_import_empty_is_error(self):
        self.assertFalse(ImportResearchTool(self.vault).run("").success)

    def test_summarise_loads_note(self):                # vault:summarise
        imp = ImportResearchTool(self.vault).run("# Topic\n\nbody alpha bravo charlie")
        r = SummariseResearchTool(self.vault).run(imp.metadata["path"])
        self.assertTrue(r.success)
        self.assertIn("body alpha bravo charlie", r.output)
        self.assertIn("Research Note", r.output)

    def test_summarise_missing_is_error(self):
        self.assertFalse(SummariseResearchTool(self.vault).run("does-not-exist.md").success)

    def test_summarise_resolves_path_without_md_extension(self):   # T5.10
        imp = ImportResearchTool(self.vault).run("# Topic\n\nbody text here")
        rel_no_ext = imp.metadata["path"][:-3]                     # strip .md
        r = SummariseResearchTool(self.vault).run(rel_no_ext)
        self.assertTrue(r.success)                                 # used to be "not found"
        self.assertIn("body text here", r.output)

    def test_summarise_resolves_bare_name(self):                   # T5.10 — name only
        imp = ImportResearchTool(self.vault).run("# Topic\n\nbody text here")
        name = Path(imp.metadata["path"]).name
        self.assertTrue(SummariseResearchTool(self.vault).run(name).success)

    def test_summarize_american_spelling_is_aliased(self):         # T5.10 — vault:summarize
        from assistant_core.vault_commands import VAULT_COMMANDS
        from assistant_core.agent_loop import VAULT_COMMANDS as LOOP_CMDS
        self.assertEqual(VAULT_COMMANDS["vault:summarize"][0], "summarise_research")
        self.assertEqual(LOOP_CMDS["vault:summarize"], "summarise_research")

    def test_import_uses_title_fn_for_slug_and_heading(self):   # M20 — short LLM title
        t = ImportResearchTool(self.vault, title_fn=lambda c: "Rocket Mass Heater")
        r = t.run("A rocket mass heater is a wood-burning system that ... [long first sentence]")
        self.assertEqual(r.metadata["title"], "Rocket Mass Heater")
        self.assertIn("rocket-mass-heater", r.metadata["path"])      # slug from the title
        body = (Path(self.vault) / r.metadata["path"]).read_text(encoding="utf-8")
        self.assertIn("# Rocket Mass Heater", body)                  # heading from the title
        self.assertNotIn("a-rocket-mass-heater-is-a", r.metadata["path"])

    def test_import_falls_back_when_title_fn_fails(self):        # heuristic slug still works
        def _boom(_): raise RuntimeError("no model")
        r = ImportResearchTool(self.vault, title_fn=_boom).run("Riser height matters most here")
        self.assertTrue(r.success)
        self.assertIn("riser-height-matters", r.metadata["path"])

    def test_import_unique_filename_same_day(self):     # T5.08
        t = ImportResearchTool(self.vault)
        r1 = t.run("# Same Topic\n\nfirst")
        r2 = t.run("# Same Topic\n\nsecond")
        self.assertNotEqual(r1.metadata["path"], r2.metadata["path"])
        self.assertTrue((Path(self.vault) / r1.metadata["path"]).exists())
        self.assertTrue((Path(self.vault) / r2.metadata["path"]).exists())


if __name__ == "__main__":
    unittest.main()
