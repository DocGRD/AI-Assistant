"""T5.14 — full-text vault search: all-words fallback + episode-log exclusion. Stdlib."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.tools.search_vault import SearchVaultTool


class SearchVaultTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        self._write("AI/Memory/Projects/Research-Test.md",
                    "Bluebirds hunt by perching and swooping down to catch prey. "
                    "They belong to the genus Sialia.")
        # an episode log that recorded a past search of the same words
        self._write("AI/Memory/Episodes/2026-07-01.md",
                    "- **07:00** `search_vault` — down to catch prey")
        self.tool = SearchVaultTool(str(self.vault))

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_exact_phrase_finds_note_not_episode(self):
        r = self.tool.run("down to catch prey")
        self.assertIn("Research-Test.md", r.output)
        self.assertNotIn("Episodes", r.output)          # episode log excluded

    def test_all_words_fallback_when_phrase_absent(self):
        # words present but not as a contiguous phrase / reordered
        r = self.tool.run("prey bluebirds Sialia")
        self.assertIn("Research-Test.md", r.output)
        self.assertIn("all the words", r.output)         # signalled the fallback

    def test_single_distinctive_word(self):
        self.assertIn("Research-Test.md", self.tool.run("Sialia").output)

    def test_missing_word_yields_no_match(self):
        r = self.tool.run("bluebirds penguins")          # penguins absent
        self.assertIn("No notes found", r.output)

    def test_episode_only_query_is_excluded(self):
        # the phrase exists ONLY in the episode log → excluded → no match
        r = self.tool.run("07:00 search_vault")
        self.assertIn("No notes found", r.output)

    def test_config_exclude_folder(self):
        self._write("06 - Projects/Camping.md", "Sialia bluebird camping notes")
        tool = SearchVaultTool(str(self.vault), {"search_exclude_folders": ["06 - Projects"]})
        r = tool.run("Sialia")
        self.assertIn("Research-Test.md", r.output)         # AI/Memory/Projects still searched
        self.assertNotIn("Camping.md", r.output)            # excluded folder skipped

    def test_config_include_only_whitelist(self):
        self._write("06 - Projects/Camping.md", "Sialia bluebird camping notes")
        tool = SearchVaultTool(str(self.vault), {"search_include_folders": ["06 - Projects"]})
        r = tool.run("Sialia")
        self.assertIn("Camping.md", r.output)               # only the whitelisted folder
        self.assertNotIn("Research-Test.md", r.output)      # AI/Memory not in whitelist


if __name__ == "__main__":
    unittest.main()
