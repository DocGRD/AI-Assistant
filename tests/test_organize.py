"""M34 — auto-organize (propose-only tags + validated related links)."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from assistant_core.proactive import organize
from assistant_core.background import governor
from assistant_core import feedback


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
        self._orig_pending = organize._PENDING_FILE
        organize._STATE_FILE = Path(self.tmp) / "organize_state.json"
        organize._PENDING_FILE = Path(self.tmp) / "organize_pending.json"
        # isolate feedback so accept/reject counts don't leak between tests or real data/
        self._orig_fb = feedback._FILE
        feedback._FILE = Path(self.tmp) / "feedback.json"

    def tearDown(self):
        organize._STATE_FILE = self._orig_state
        organize._PENDING_FILE = self._orig_pending
        feedback._FILE = self._orig_fb

    def test_apply_suggestion_commits_and_revalidates(self):
        note = Path(self.tmp) / "Apply Me.md"
        note.write_text("Body here.", encoding="utf-8")
        (Path(self.tmp) / "Neighbour.md").write_text("x", encoding="utf-8")
        organize._save_pending([{"note": "Apply Me.md", "tags": ["faith"], "related": ["Neighbour"]}])
        ok = organize.apply_suggestion(self.tmp, "Apply Me.md", ["faith", "prayer"],
                                       ["Neighbour", "Ghost Note"])   # Ghost doesn't exist
        self.assertTrue(ok)
        txt = note.read_text(encoding="utf-8")
        self.assertIn("tags: [faith, prayer]", txt)     # merged into frontmatter
        self.assertIn("## Related", txt)
        self.assertIn("[[Neighbour]]", txt)
        self.assertNotIn("Ghost Note", txt)             # re-validated at apply → dropped
        self.assertEqual(organize.load_pending(), [])   # removed from pending after apply

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


class PerItemTests(unittest.TestCase):
    """M35.1 — granular per-tag/per-link apply + dismiss + feedback learning."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        (v / "Note.md").write_text("Body.\n", encoding="utf-8")
        (v / "Neighbour.md").write_text("x", encoding="utf-8")
        (v / "Other.md").write_text("y", encoding="utf-8")
        self._orig_pending = organize._PENDING_FILE
        organize._PENDING_FILE = v / "organize_pending.json"
        self._orig_fb = feedback._FILE
        feedback._FILE = v / "feedback.json"
        organize._save_pending([{"note": "Note.md",
                                 "tags": ["faith", "prayer"],
                                 "related": ["Neighbour", "Other"]}])

    def tearDown(self):
        organize._PENDING_FILE = self._orig_pending
        feedback._FILE = self._orig_fb

    def test_apply_one_tag_leaves_others_pending(self):
        ok = organize.apply_one(self.tmp, "Note.md", "tag", "faith")
        self.assertTrue(ok)
        txt = (Path(self.tmp) / "Note.md").read_text(encoding="utf-8")
        self.assertIn("faith", txt)
        self.assertNotIn("prayer", txt)                      # only the one tag applied
        pend = organize.load_pending()[0]
        self.assertEqual(pend["tags"], ["prayer"])           # the other tag still pending
        self.assertEqual(pend["related"], ["Neighbour", "Other"])
        self.assertTrue(feedback.boosted("tag", "faith"))    # accept recorded

    def test_apply_one_link_adds_related(self):
        ok = organize.apply_one(self.tmp, "Note.md", "link", "Neighbour")
        self.assertTrue(ok)
        txt = (Path(self.tmp) / "Note.md").read_text(encoding="utf-8")
        self.assertIn("## Related", txt)
        self.assertIn("[[Neighbour]]", txt)
        self.assertNotIn("[[Other]]", txt)
        self.assertEqual(organize.load_pending()[0]["related"], ["Other"])

    def test_apply_one_fabricated_link_rejected(self):
        self.assertFalse(organize.apply_one(self.tmp, "Note.md", "link", "Ghost"))
        self.assertNotIn("Ghost", (Path(self.tmp) / "Note.md").read_text(encoding="utf-8"))

    def test_resolving_last_items_drops_note(self):
        for kind, val in [("tag", "faith"), ("tag", "prayer"),
                          ("link", "Neighbour"), ("link", "Other")]:
            organize.apply_one(self.tmp, "Note.md", kind, val)
        self.assertEqual(organize.load_pending(), [])        # note fully resolved → gone

    def test_rejected_tag_suppressed_next_run(self):
        # reject the same tag twice → suppressed globally
        organize.reject_one("Note.md", "tag", "prayer")
        organize.reject_one("Other.md", "tag", "prayer")
        self.assertTrue(feedback.suppressed("tag", "prayer"))

        class _Rambler:
            available_providers = ["groq"]
            def generate(self, messages, **kw):
                return "prayer, faith", "groq"
        tags = organize._suggest_tags(_Rambler(), "content", ["faith"])
        self.assertNotIn("prayer", tags)                     # suppressed suggestion dropped
        self.assertIn("faith", tags)

    def test_rejected_link_suppressed_for_that_note(self):
        organize.reject_one("Note.md", "link", "Other")
        organize.reject_one("Note.md", "link", "Other")      # per-note scope
        rag = _FakeRag([{"path": "Other.md"}, {"path": "Neighbour.md"}])
        links = organize._related_links(rag, "Note.md", self.tmp)
        self.assertNotIn("Other", links)                     # rejected on this note
        self.assertIn("Neighbour", links)
        # a different note is unaffected
        links2 = organize._related_links(rag, "Elsewhere.md", self.tmp)
        self.assertIn("Other", links2)

    def test_reject_all_records_rejects(self):
        organize.reject_all("Note.md")
        self.assertEqual(organize.load_pending(), [])
        c = feedback.counts("tag", "faith")
        self.assertEqual(c["reject"], 1)

    def test_apply_folder_moves_note(self):        # M38 auto-filing
        organize._save_pending([{"note": "Note.md", "tags": [], "related": [],
                                 "folder": "Projects", "project": ""}])
        ok = organize.apply_one(self.tmp, "Note.md", "folder", "Projects")
        self.assertTrue(ok)
        self.assertTrue((Path(self.tmp) / "Projects" / "Note.md").exists())
        self.assertFalse((Path(self.tmp) / "Note.md").exists())
        self.assertEqual(organize.load_pending(), [])          # moved → entry dropped

    def test_apply_folder_rejects_system_dir(self):
        organize._save_pending([{"note": "Note.md", "tags": [], "related": [], "folder": "AI/System", "project": ""}])
        self.assertFalse(organize.apply_one(self.tmp, "Note.md", "folder", "AI/System"))
        self.assertTrue((Path(self.tmp) / "Note.md").exists())  # not moved

    def test_apply_project_sets_frontmatter(self):  # M38 project association
        organize._save_pending([{"note": "Note.md", "tags": [], "related": [], "folder": "", "project": "Homestead"}])
        ok = organize.apply_one(self.tmp, "Note.md", "project", "Homestead")
        self.assertTrue(ok)
        self.assertIn("project: Homestead", (Path(self.tmp) / "Note.md").read_text(encoding="utf-8"))
        self.assertEqual(organize.load_pending(), [])


if __name__ == "__main__":
    unittest.main()


class TestMergeTags(unittest.TestCase):
    """Regression: block-style YAML tags used to corrupt on merge (stray '-' + orphaned list lines)."""

    def _fm(self, text: str) -> str:
        return text.split("---")[1].strip()

    def test_block_style_stays_clean(self):
        t = "---\ntitle: X\ntags:\n  - clippings\n---\n\nbody"
        out = self._fm(organize._merge_tags(t, ["analysis", "software"]))
        self.assertIn("tags: [analysis, clippings, software]", out)
        self.assertNotIn("- clippings", out)     # no orphaned block list item
        self.assertNotIn("[-", out)              # no stray dash tag

    def test_repairs_previously_corrupted_frontmatter(self):
        corrupted = "---\ntitle: X\ntags: [-, analysis, clippings, development]\n  - clippings\n---\n\nbody"
        out = self._fm(organize._merge_tags(corrupted, []))
        self.assertEqual(out, "title: X\ntags: [analysis, clippings, development]")

    def test_flow_style_merges(self):
        out = self._fm(organize._merge_tags("---\ntags: [a, b]\ntitle: X\n---\nbody", ["c"]))
        self.assertIn("tags: [a, b, c]", out)

    def test_adds_tags_when_absent(self):
        out = self._fm(organize._merge_tags("---\ntitle: X\n---\nbody", ["new"]))
        self.assertIn("tags: [new]", out)

    def test_no_frontmatter_gets_one(self):
        self.assertTrue(organize._merge_tags("just body", ["x"]).startswith("---\ntags: [x]\n---"))
