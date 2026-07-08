"""
Goal worker — Milestone 35.

A daemon thread that advances *running* goals one subtask at a time, **governor-paced**
(the M34 resource governor: yields to the foreground, respects the hourly budget). One
subtask per tick keeps a long goal spread gradually over time so it never competes with
the user or blows the free-tier quota. Fully resumable — all state lives in the goal store.

Decoupled from the agent loop: it's handed a `run_subtask(instruction) -> str` callable
(production wires this to the agent loop; tests pass a fake).
"""

import logging
import threading

logger = logging.getLogger("assistant")


class GoalWorker:
    def __init__(self, vault_path, config: dict, run_subtask, tick_seconds: int = 60):
        self._vault      = vault_path
        self._config     = config
        self._run_subtask = run_subtask
        self._tick       = tick_seconds
        self._stop       = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"[Goals] worker started (tick {self._tick}s, governor-paced).")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick_once()
            except Exception as exc:
                logger.warning(f"[Goals] worker tick failed: {exc}")
            self._stop.wait(self._tick)

    def tick_once(self) -> bool:
        """Advance at most one subtask of one running goal. Returns True if it ran one."""
        from assistant_core.goals import store
        from assistant_core.background import governor

        for goal in store.load_goals():
            if goal["status"] != "running" or not store.due(goal):   # M39 — recurring not-yet-due
                continue
            sub = store.next_pending(goal)
            if sub is None:                                  # nothing left
                if store.rearm_recurring(goal):              # M39 — recurring goal loops
                    store.render_note(self._vault, store.get_goal(goal["slug"]))
                    continue
                store.set_status(goal["slug"], "done")
                store.render_note(self._vault, store.get_goal(goal["slug"]))
                logger.info(f"[Goals] '{goal['slug']}' complete.")
                continue
            if not governor.may_run(self._config):           # foreground busy / budget spent
                logger.debug("[Goals] deferring — governor.")
                return False
            if not store.budget_ok(goal):                    # M39 — per-goal daily cap
                logger.info(f"[Goals] '{goal['slug']}' hit its daily budget — pausing until tomorrow.")
                continue
            logger.info(f"[Goals] '{goal['slug']}' step {sub['id']+1}: {sub['task'][:80]}")
            try:
                result = self._run_subtask(sub["task"])
                sub["status"], sub["result"] = "done", (result or "").strip()[:400]
            except Exception as exc:
                sub["status"], sub["result"] = "failed", f"error: {exc}"
                logger.warning(f"[Goals] step failed: {exc}")
            governor.record_background_call()
            store.record_spend(goal)                         # M39 — count against the goal's budget
            store.upsert_goal(goal)
            store.render_note(self._vault, goal)
            return True                                      # one subtask per tick (paced)
        return False
