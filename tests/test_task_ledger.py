"""M20 Slice 3 — externalized task/planner state. Stdlib unittest."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.task_ledger import TaskLedger


class TaskLedgerTests(unittest.TestCase):
    def test_first_step_renders_goal_and_empty(self):
        led = TaskLedger(goal="reorganise the projects folder")
        out = led.render(1, 10)
        self.assertIn("reorganise the projects folder", out)
        self.assertIn("nothing yet", out)
        self.assertIn("step 1 of at most 10", out)

    def test_checkpoints_appear(self):
        led = TaskLedger(goal="find rocket stove notes")
        led.record(1, "groq", "vault:search", True, "rocket stove")
        led.record(2, "groq", "vault:read", False, "Foo — not found")
        out = led.render(3, 10)
        self.assertIn("✓ step 1 (groq): vault:search rocket stove", out)
        self.assertIn("✗ step 2 (groq): vault:read", out)

    def test_provider_switch_flagged(self):
        led = TaskLedger(goal="g")
        led.note_provider("groq")
        self.assertFalse(led.switched)
        led.note_provider("cerebras")        # switch mid-task
        self.assertTrue(led.switched)
        self.assertIn("changed to cerebras mid-task", led.render(2, 10))

    def test_only_recent_checkpoints_shown(self):
        led = TaskLedger(goal="g")
        for i in range(1, 13):
            led.record(i, "groq", f"vault:read-{i}", True, "x")
        out = led.render(13, 20)
        self.assertNotIn("vault:read-1 ", out)   # oldest trimmed (last 8 only)
        self.assertIn("vault:read-12", out)      # most recent kept


class TaskLedgerPersistenceTests(unittest.TestCase):
    def test_persist_writes_inspectable_note(self):
        with tempfile.TemporaryDirectory() as d:
            led = TaskLedger(goal="reorganise projects")
            led.persist_path = Path(d) / "AI" / "System" / "Task-State.md"
            led.record(1, "groq", "vault:search", True, "projects")
            led.note_provider("groq")
            led.persist("in-progress", 1, 10)
            text = (Path(d) / "AI" / "System" / "Task-State.md").read_text(encoding="utf-8")
            self.assertIn("reorganise projects", text)
            self.assertIn("Status:** in-progress", text)
            self.assertIn("✓ step 1 (groq): vault:search", text)

    def test_persist_without_path_is_noop(self):
        TaskLedger(goal="g").persist("done")     # no persist_path → must not raise


if __name__ == "__main__":
    unittest.main()
