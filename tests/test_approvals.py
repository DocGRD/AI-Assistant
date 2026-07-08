"""M36 (C1) — unified Approvals inbox: normalize + dispatch across organize/memory/goals."""

import tempfile
import unittest
from pathlib import Path

from assistant_core import approvals, feedback, consolidation
from assistant_core.proactive import organize
from assistant_core.goals import store as goals_store


class ApprovalsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        (v / "Note.md").write_text("Body.\n", encoding="utf-8")
        (v / "Neighbour.md").write_text("x", encoding="utf-8")
        # organize pending
        self._op = organize._PENDING_FILE
        organize._PENDING_FILE = v / "organize_pending.json"
        organize._save_pending([{"note": "Note.md", "tags": ["faith"], "related": ["Neighbour"]}])
        # feedback isolation
        self._fb = feedback._FILE
        feedback._FILE = v / "feedback.json"
        # goals isolation
        self._gf = goals_store._GOALS_FILE
        goals_store._GOALS_FILE = v / "goals.json"
        # memory consolidation proposal
        pdir = v / consolidation.PROPOSED_DIR
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "consolidation-2026-07-08.md").write_text(
            "# Proposed new facts\n\n- [ ] User prefers zero-cost tools\n- [ ] Box runs on the LAN\n",
            encoding="utf-8")

    def tearDown(self):
        organize._PENDING_FILE = self._op
        feedback._FILE = self._fb
        goals_store._GOALS_FILE = self._gf

    def test_list_normalizes_all_kinds(self):
        goals_store.create_goal("Research rocket stoves", ["step a", "step b"])  # status=proposed
        items = approvals.list_approvals(self.tmp)
        kinds = {a["kind"] for a in items}
        self.assertEqual(kinds, {"organize", "memory", "goal"})
        org = next(a for a in items if a["kind"] == "organize")
        self.assertEqual({i["itemkind"] for i in org["items"]}, {"tag", "link"})
        goal = next(a for a in items if a["kind"] == "goal")
        self.assertTrue(goal["whole_only"])

    def test_apply_one_organize_tag(self):
        aid = "organize:Note.md"
        r = approvals.apply_approval(self.tmp, aid, {"itemkind": "tag", "value": "faith", "label": "#faith"})
        self.assertTrue(r["applied"])
        self.assertIn("faith", (Path(self.tmp) / "Note.md").read_text(encoding="utf-8"))
        # link still pending
        org = next(a for a in approvals.list_approvals(self.tmp) if a["kind"] == "organize")
        self.assertEqual([i["value"] for i in org["items"]], ["Neighbour"])

    def test_apply_one_memory_fact(self):
        aid = "memory:consolidation-2026-07-08.md"
        r = approvals.apply_approval(self.tmp, aid,
                                     {"itemkind": "fact", "value": "User prefers zero-cost tools", "label": "…"})
        self.assertTrue(r["applied"])
        facts = (Path(self.tmp) / consolidation.FACTS_FILE).read_text(encoding="utf-8")
        self.assertIn("User prefers zero-cost tools", facts)
        self.assertTrue(feedback.boosted("fact", "User prefers zero-cost tools"))
        # other fact remains
        mem = next(a for a in approvals.list_approvals(self.tmp) if a["kind"] == "memory")
        self.assertEqual([i["value"] for i in mem["items"]], ["Box runs on the LAN"])

    def test_reject_one_memory_fact_records_feedback(self):
        aid = "memory:consolidation-2026-07-08.md"
        approvals.reject_approval(self.tmp, aid,
                                  {"itemkind": "fact", "value": "Box runs on the LAN", "label": "…"})
        self.assertEqual(feedback.counts("fact", "Box runs on the LAN")["reject"], 1)
        mem = next(a for a in approvals.list_approvals(self.tmp) if a["kind"] == "memory")
        self.assertEqual([i["value"] for i in mem["items"]], ["User prefers zero-cost tools"])

    def test_apply_goal_sets_running(self):
        g = goals_store.create_goal("Do a thing", ["only step"])
        r = approvals.apply_approval(self.tmp, f"goal:{g['slug']}")
        self.assertTrue(r["applied"])
        self.assertEqual(goals_store.get_goal(g["slug"])["status"], "running")

    def test_reject_goal_cancels(self):
        g = goals_store.create_goal("Do a thing", ["only step"])
        approvals.reject_approval(self.tmp, f"goal:{g['slug']}")
        self.assertEqual(goals_store.get_goal(g["slug"])["status"], "cancelled")

    def test_whole_organize_apply(self):
        r = approvals.apply_approval(self.tmp, "organize:Note.md")
        self.assertTrue(r["applied"])
        txt = (Path(self.tmp) / "Note.md").read_text(encoding="utf-8")
        self.assertIn("faith", txt)
        self.assertIn("[[Neighbour]]", txt)
        self.assertEqual([a for a in approvals.list_approvals(self.tmp) if a["kind"] == "organize"], [])


if __name__ == "__main__":
    unittest.main()
