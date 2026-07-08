"""
Goal store — Milestone 35.

Persistent, resumable state for background goals. The canonical record is
`data/goals.json` (survives restarts); a human-readable mirror is written to
`AI/System/Goals/<slug>.md` so the user can watch progress in Obsidian.

A goal:
  {slug, description, status, estimate, created, subtasks: [{id, task, status, result}]}
status:   proposed | running | paused | done | cancelled
subtask:  pending  | done    | failed
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from assistant_core.paths import DATA_DIR

logger = logging.getLogger("assistant")

_GOALS_FILE = DATA_DIR / "goals.json"
GOALS_DIR   = "AI/System/Goals"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:40] or "goal")


def load_goals() -> list[dict]:
    try:
        return json.loads(_GOALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_goals(goals: list[dict]) -> None:
    try:
        _GOALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _GOALS_FILE.write_text(json.dumps(goals, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"[Goals] save failed: {exc}")


def get_goal(slug: str) -> dict | None:
    return next((g for g in load_goals() if g["slug"] == slug), None)


def upsert_goal(goal: dict) -> None:
    goals = load_goals()
    for i, g in enumerate(goals):
        if g["slug"] == goal["slug"]:
            goals[i] = goal
            break
    else:
        goals.append(goal)
    save_goals(goals)


def create_goal(description: str, subtasks: list[str], estimate: str = "") -> dict:
    base = slugify(description)
    existing = {g["slug"] for g in load_goals()}
    slug, n = base, 2
    while slug in existing:
        slug = f"{base}-{n}"; n += 1
    goal = {
        "slug": slug, "description": description, "status": "proposed",
        "estimate": estimate, "created": datetime.now().isoformat(timespec="seconds"),
        "subtasks": [{"id": i, "task": t, "status": "pending", "result": ""}
                     for i, t in enumerate(subtasks)],
    }
    upsert_goal(goal)
    return goal


def set_status(slug: str, status: str) -> dict | None:
    g = get_goal(slug)
    if g:
        g["status"] = status
        upsert_goal(g)
    return g


def next_pending(goal: dict) -> dict | None:
    return next((s for s in goal["subtasks"] if s["status"] == "pending"), None)


def progress(goal: dict) -> tuple[int, int]:
    done = sum(1 for s in goal["subtasks"] if s["status"] == "done")
    return done, len(goal["subtasks"])


def render_note(vault, goal: dict) -> str:
    """Write the human-readable mirror to AI/System/Goals/<slug>.md; return the rel path."""
    done, total = progress(goal)
    lines = [f"# Goal: {goal['description']}", "",
             f"*Status: **{goal['status']}** · {done}/{total} steps done*",
             (f"*Estimate: {goal['estimate']}*" if goal.get("estimate") else ""), "", "## Plan", ""]
    icon = {"done": "x", "pending": " ", "failed": "!"}
    for s in goal["subtasks"]:
        lines.append(f"- [{icon.get(s['status'], ' ')}] {s['task']}")
        if s["status"] == "done" and s["result"]:
            lines.append(f"      ↳ {s['result'][:200]}")
    rel = f"{GOALS_DIR}/{goal['slug']}.md"
    try:
        dest = Path(vault) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(x for x in lines if x is not None), encoding="utf-8")
    except Exception as exc:
        logger.debug(f"[Goals] note write failed: {exc}")
    return rel
