"""M34 — daily briefing (read-only proactive agent)."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from assistant_core.proactive import briefing


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        (v / "Recent Note.md").write_text("hello", encoding="utf-8")           # counts as recent
        (v / "AI/System").mkdir(parents=True)
        (v / "AI/System/System-Prompt.md").write_text("x", encoding="utf-8")   # excluded
        (v / "AI/Memory/proposed").mkdir(parents=True)
        (v / "AI/Memory/proposed/consolidation-2026-07-08.md").write_text("p", encoding="utf-8")

    def test_recent_notes_excludes_system(self):
        rc = briefing.recent_notes(self.tmp, hours=24)
        self.assertIn("Recent Note.md", rc)
        self.assertNotIn("AI/System/System-Prompt.md", rc)

    def test_pending_proposals(self):
        p = briefing.pending_proposals(self.tmp)
        self.assertEqual(p, ["AI/Memory/proposed/consolidation-2026-07-08.md"])

    def test_build_briefing_sections(self):
        md = briefing.build_briefing(self.tmp, router=None)   # no focus line without a router
        self.assertIn("# Daily Briefing —", md)
        self.assertIn("## Recently changed", md)
        self.assertIn("[[Recent Note]]", md)
        self.assertIn("## Flashcards due (0)", md)
        self.assertIn("## Awaiting your approval (1)", md)
        self.assertIn("consolidation-2026-07-08.md", md)
        self.assertNotIn("## Focus", md)                      # skipped with no router

    def test_write_briefing_creates_dated_file(self):
        rel = briefing.write_briefing(self.tmp, now=datetime(2026, 7, 8, 6, 0))
        self.assertEqual(rel, "AI/Briefings/2026-07-08.md")
        self.assertTrue((Path(self.tmp) / rel).exists())
        # read-only: the source note is untouched
        self.assertEqual((Path(self.tmp) / "Recent Note.md").read_text(encoding="utf-8"), "hello")


class SchedulerDecisionTests(unittest.TestCase):
    def test_daily_due(self):
        from assistant_core.scheduler import daily_due
        now = datetime(2026, 7, 8, 6, 0)
        self.assertTrue(daily_due(now, 6, None))
        self.assertFalse(daily_due(now, 6, "2026-07-08"))     # already fired today
        self.assertFalse(daily_due(now, 5, None))             # wrong hour


if __name__ == "__main__":
    unittest.main()
