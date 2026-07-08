"""M35 — goal engine: store, planner parse, governor-paced worker."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.goals import store, planner, worker
from assistant_core.background import governor


class PlannerParseTests(unittest.TestCase):
    def test_parse_steps_and_estimate(self):
        text = ("Sure!\nSTEPS:\n1. Use vault:webresearch to find X\n2. Create a note at AI/Library/x.md\n"
                "3) Link it to related notes\nESTIMATE: ~3 steps, a few model calls, runs in the background")
        plan = planner.parse_plan(text)
        self.assertEqual(len(plan["subtasks"]), 3)
        self.assertIn("vault:webresearch", plan["subtasks"][0])
        self.assertIn("background", plan["estimate"])

    def test_empty_when_no_steps(self):
        self.assertEqual(planner.parse_plan("no plan here")["subtasks"], [])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = store._GOALS_FILE
        store._GOALS_FILE = Path(self.tmp) / "goals.json"

    def tearDown(self):
        store._GOALS_FILE = self._orig

    def test_create_and_progress(self):
        g = store.create_goal("Get Matthew Henry commentary", ["step a", "step b"], "~2 steps")
        self.assertEqual(g["status"], "proposed")
        self.assertEqual(store.progress(g), (0, 2))
        self.assertEqual(store.next_pending(g)["task"], "step a")

    def test_slug_uniqueness(self):
        a = store.create_goal("Same title", ["x"])
        b = store.create_goal("Same title", ["y"])
        self.assertNotEqual(a["slug"], b["slug"])

    def test_status_and_note(self):
        g = store.create_goal("Do a thing", ["only step"])
        store.set_status(g["slug"], "running")
        rel = store.render_note(self.tmp, store.get_goal(g["slug"]))
        self.assertEqual(rel, f"AI/System/Goals/{g['slug']}.md")
        note = (Path(self.tmp) / rel).read_text(encoding="utf-8")
        self.assertIn("Status: **running**", note)
        self.assertIn("- [ ] only step", note)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        governor._reset_for_tests()
        self.tmp = tempfile.mkdtemp()
        self._orig = store._GOALS_FILE
        store._GOALS_FILE = Path(self.tmp) / "goals.json"
        self.ran = []

    def tearDown(self):
        store._GOALS_FILE = self._orig

    def _worker(self):
        def run_subtask(instr):
            self.ran.append(instr)
            return f"did: {instr}"
        return worker.GoalWorker(self.tmp, {}, run_subtask)

    def test_advances_one_subtask_per_tick(self):
        g = store.create_goal("g", ["s1", "s2"])
        store.set_status(g["slug"], "running")
        w = self._worker()
        self.assertTrue(w.tick_once())               # runs s1
        self.assertEqual(self.ran, ["s1"])
        self.assertTrue(w.tick_once())               # runs s2
        self.assertEqual(self.ran, ["s1", "s2"])
        w.tick_once()                                # no pending → marks done
        self.assertEqual(store.get_goal(g["slug"])["status"], "done")

    def test_governor_pauses_worker(self):
        g = store.create_goal("g", ["s1"])
        store.set_status(g["slug"], "running")
        governor.mark_foreground_activity(cooldown_s=999)   # foreground busy
        self.assertFalse(self._worker().tick_once())        # deferred, nothing ran
        self.assertEqual(self.ran, [])

    def test_proposed_goal_not_run(self):
        store.create_goal("g", ["s1"])              # status stays 'proposed'
        self.assertFalse(self._worker().tick_once())
        self.assertEqual(self.ran, [])


if __name__ == "__main__":
    unittest.main()
