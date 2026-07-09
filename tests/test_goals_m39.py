"""M39 — goal templates, recurring re-arm, per-goal budget cap, action extraction."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from assistant_core.goals import store, planner, worker
from assistant_core.background import governor
from assistant_core import tasks


class TemplateTests(unittest.TestCase):
    def test_research_template_expands(self):
        plan = planner.plan_from_template("research", "rocket stoves")
        self.assertEqual(plan["template"], "research")
        self.assertTrue(any("webresearch" in s for s in plan["subtasks"]))
        self.assertTrue(any("rocket stoves" in s for s in plan["subtasks"]))

    def test_unknown_template_none(self):
        self.assertIsNone(planner.plan_from_template("nope", "x"))
        self.assertIsNone(planner.plan_from_template("research", ""))

    def test_detect_template(self):
        self.assertEqual(planner.detect_template("digest my meeting notes"), "digest")
        self.assertIsNone(planner.detect_template("write a poem"))


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._g = store._GOALS_FILE
        store._GOALS_FILE = Path(self.tmp) / "goals.json"

    def tearDown(self):
        store._GOALS_FILE = self._g

    def test_budget_cap(self):
        g = store.create_goal("g", ["a", "b", "c"], budget=2)
        now = datetime(2026, 7, 8, 9, 0)
        self.assertTrue(store.budget_ok(g, now))
        store.record_spend(g, now); store.record_spend(g, now)
        self.assertFalse(store.budget_ok(g, now))                 # 2 spent, cap 2
        self.assertTrue(store.budget_ok(g, now + timedelta(days=1)))   # resets next day

    def test_recurring_rearm(self):
        g = store.create_goal("weekly review", ["step"], recurring="weekly")
        for s in g["subtasks"]:
            s["status"] = "done"
        now = datetime(2026, 7, 8, 9, 0)
        self.assertTrue(store.rearm_recurring(g, now))
        self.assertEqual(g["subtasks"][0]["status"], "pending")   # reset
        self.assertFalse(store.due(g, now))                       # scheduled for later
        self.assertTrue(store.due(g, now + timedelta(days=8)))

    def test_non_recurring_not_rearmed(self):
        g = store.create_goal("one-off", ["step"])
        self.assertFalse(store.rearm_recurring(g))

    def test_next_pending_respects_deps(self):     # M39 carried-forward: subtask DAG
        g = store.create_goal("g", [{"task": "a"}, {"task": "b", "deps": [0]}])
        self.assertEqual(store.next_pending(g)["task"], "a")   # b waits on a
        g["subtasks"][0]["status"] = "done"
        self.assertEqual(store.next_pending(g)["task"], "b")   # a done → b runnable

    def test_failed_dep_blocks_subtask(self):
        g = store.create_goal("g", [{"task": "a"}, {"task": "b", "deps": [0]}])
        g["subtasks"][0]["status"] = "failed"
        self.assertIsNone(store.next_pending(g))              # b can never run

    def test_set_subtasks_replans(self):                     # v1.8 — replan
        g = store.create_goal("g", ["old1", "old2"])
        store.set_subtasks(g["slug"], ["new a", "new b", "new c"])
        g2 = store.get_goal(g["slug"])
        self.assertEqual([s["task"] for s in g2["subtasks"]], ["new a", "new b", "new c"])
        self.assertTrue(all(s["status"] == "pending" for s in g2["subtasks"]))

    def test_plan_edits_in_note_are_honored(self):           # v1.8 — edit the plan note
        from pathlib import Path
        g = store.create_goal("g", ["step a", "step b"])
        store.render_note(self.tmp, g)
        p = Path(self.tmp) / "AI" / "System" / "Goals" / f"{g['slug']}.md"
        t = p.read_text(encoding="utf-8").replace("- [ ] step a", "- [ ] edited a\n- [ ] extra step")
        p.write_text(t, encoding="utf-8")
        steps = store.plan_steps_from_note(self.tmp, g["slug"])
        self.assertEqual(steps, ["edited a", "extra step", "step b"])   # user's edited plan

    def test_worker_recurring_loops_not_done(self):
        governor._reset_for_tests()
        g = store.create_goal("daily digest", ["only step"], recurring="daily")
        store.set_status(g["slug"], "running")
        ran = []
        w = worker.GoalWorker(self.tmp, {}, lambda t: ran.append(t) or "ok")
        self.assertTrue(w.tick_once())                            # runs the step
        w.tick_once()                                             # no pending → re-arm (not done)
        g2 = store.get_goal(g["slug"])
        self.assertEqual(g2["status"], "running")                 # recurring stays running
        self.assertTrue(g2.get("not_before"))                     # scheduled for next run


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_extract_checkboxes_and_markers(self):
        text = ("# Meeting\n- [ ] Email Bob about the budget\n- [x] Already done\n"
                "TODO: book the venue\nWe should follow up with the vendor.\n")
        acts = tasks.extract_actions(text)
        self.assertIn("Email Bob about the budget", acts)
        self.assertTrue(any("book the venue" in a for a in acts))
        self.assertTrue(any("follow up with the vendor" in a.lower() for a in acts))
        self.assertNotIn("Already done", acts)                    # checked → not an open action

    def test_write_actions_propose_only(self):
        v = Path(self.tmp)
        (v / "Note.md").write_text("- [ ] Do the thing\nTODO: buy milk\n", encoding="utf-8")
        rel, n = tasks.write_actions(self.tmp, "Note.md")
        self.assertEqual(rel, "AI/Tasks/Note.md")
        self.assertEqual(n, 2)
        out = (v / rel).read_text(encoding="utf-8")
        self.assertIn("- [ ] Do the thing", out)
        self.assertIn("[[Note]]", out)
        # source untouched
        self.assertNotIn("Actions —", (v / "Note.md").read_text(encoding="utf-8"))

    def test_open_actions_for_briefing(self):
        v = Path(self.tmp)
        (v / "Note.md").write_text("- [ ] Do the thing\n", encoding="utf-8")
        tasks.write_actions(self.tmp, "Note.md")
        opens = tasks.open_actions(self.tmp)
        self.assertTrue(any("Do the thing" in o for o in opens))

    def test_no_actions_returns_none(self):
        v = Path(self.tmp)
        (v / "Plain.md").write_text("Just some prose with no tasks at all.", encoding="utf-8")
        self.assertEqual(tasks.write_actions(self.tmp, "Plain.md"), (None, 0))


if __name__ == "__main__":
    unittest.main()
