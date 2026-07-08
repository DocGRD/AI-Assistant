"""M34 — auto-organize (propose-only tags + validated related links)."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from assistant_core.proactive import organize
from assistant_core.background import governor


class _FakeRouter:
    available_providers = ["groq"]
    def generate(self, messages, task=None, private=False, allow_webui=True, **kw):
        return "Faith, Prayer, scripture, prayer", "groq"   # dup + case handled


class _FakeRag:
    def __init__(self, related):
        self._related = related
    def has_index(self):
        return True
    def relevant_notes(self, note_path, k=5):
        return self._related


class OrganizeTests(unittest.TestCase):
    def setUp(self):
        governor._reset_for_tests()
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        (v / "New Note.md").write_text("A note about faith and prayer.\n#faith", encoding="utf-8")
        (v / "Real Neighbour.md").write_text("related content", encoding="utf-8")   # exists
        # state file → temp, so the watermark starts clean and doesn't touch real data/
        self._orig_state = organize._STATE_FILE
        organize._STATE_FILE = Path(self.tmp) / "organize_state.json"

    def tearDown(self):
        organize._STATE_FILE = self._orig_state

    def test_existing_tags_scanned(self):
        self.assertIn("faith", organize.existing_tags(self.tmp))

    def test_related_links_validated(self):
        rag = _FakeRag([{"path": "Real Neighbour.md"}, {"path": "Ghost Note.md"}])
        links = organize._related_links(rag, "New Note.md", self.tmp)
        self.assertIn("Real Neighbour", links)
        self.assertNotIn("Ghost Note", links)          # fabricated neighbour rejected

    def test_run_organize_proposes_only(self):
        rag = _FakeRag([{"path": "Real Neighbour.md"}, {"path": "Ghost Note.md"}])
        before = (Path(self.tmp) / "New Note.md").read_text(encoding="utf-8")
        rep = organize.run_organize(self.tmp, {}, rag=rag, router=_FakeRouter(),
                                    now=datetime(2026, 7, 8, 5, 0))
        # a proposal was written…
        self.assertGreaterEqual(rep["notes"], 1)
        self.assertTrue(rep["proposal"].startswith("AI/Proposed/organize-"))
        prop = (Path(self.tmp) / rep["proposal"]).read_text(encoding="utf-8")
        self.assertIn("## New Note.md", prop)
        self.assertIn("#faith", prop)                  # tags suggested (deduped/normalised)
        self.assertIn("[[Real Neighbour]]", prop)      # valid related link
        self.assertNotIn("Ghost Note", prop)           # no fabricated link
        # …but the source note is UNCHANGED (propose-only)
        self.assertEqual((Path(self.tmp) / "New Note.md").read_text(encoding="utf-8"), before)

    def test_rambling_reply_yields_clean_tags_not_junk(self):
        class _Rambler:
            available_providers = ["groq"]
            def generate(self, messages, **kw):
                return ("no matching tags, consider adding a new tag (homestead or rocket "
                        "stove), but based on the given options", "groq")
        tags = organize._suggest_tags(_Rambler(), "content", ["faith"])
        for t in tags:                                  # nothing long/hyphen-blobby survives
            self.assertLessEqual(len(t), 25)
            self.assertLessEqual(t.count("-"), 2)
        self.assertNotIn("no-matching-tags", tags)
        self.assertNotIn("consider-adding-a-new-tag-homestead-or-rocket-stove", tags)

    def test_governor_defers_stops_work(self):
        governor.mark_foreground_activity(cooldown_s=999)   # foreground "busy"
        rep = organize.run_organize(self.tmp, {}, rag=None, router=_FakeRouter(),
                                    now=datetime(2026, 7, 8, 5, 0))
        self.assertEqual(rep["scanned"], 0)                 # deferred immediately


if __name__ == "__main__":
    unittest.main()
