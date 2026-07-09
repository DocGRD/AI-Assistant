"""
Unified Approvals inbox — Milestone 36 (C1).

One normalized surface over Loremaster's *persisted* propose/commit stores:

  - **organize**  — auto-organize tag/link suggestions   (proactive/organize.py)
  - **memory**    — consolidation "durable fact" proposals (consolidation.py)
  - **goal**      — goals awaiting approval                (goals/store.py)

Each store keeps its own apply/reject logic; this module is a **thin facade** that
normalizes them to a common shape and dispatches actions back to the owning module —
so there is exactly one panel + one endpoint pair for everything that piles up in the
background, and the M35.1 per-item + open-note pattern generalizes to all of them.

Edit and restructure proposals stay inline in the chat turn on purpose: they're
synchronous (the user approves them in the moment they're produced), not background-
accumulated, so a pollable inbox adds nothing there.

Normalized approval:
    {
      "id":      "organize:Note.md",       # "<kind>:<ref>"
      "kind":    "organize"|"memory"|"goal",
      "note":    "Note.md",                 # an openable vault path (for the Open-note button)
      "summary": "…",                       # one-line headline
      "detail":  "…",                       # sub-line
      "items":   [{"itemkind": "tag", "value": "faith", "label": "#faith"}, …],
      "whole_only": bool,                   # true → no per-item actions (goals)
    }
"""

from __future__ import annotations

import logging

from assistant_core.proactive import organize
from assistant_core import consolidation
from assistant_core.goals import store as goals_store

logger = logging.getLogger("assistant")


def list_approvals(vault) -> list[dict]:
    """Every pending approval across the persisted stores, newest-relevant first."""
    out: list[dict] = []

    # organize — one approval per note; items = suggested tags + links + folder + project
    for s in organize.load_pending():
        items = [{"itemkind": "tag", "value": t, "label": f"#{t}"} for t in s.get("tags", [])]
        items += [{"itemkind": "link", "value": r, "label": f"[[{r}]]"} for r in s.get("related", [])]
        if s.get("folder"):
            items.append({"itemkind": "folder", "value": s["folder"], "label": f"→ move to {s['folder']}/"})
        if s.get("project"):
            items.append({"itemkind": "project", "value": s["project"], "label": f"project: {s['project']}"})
        if items:
            out.append({
                "id": f"organize:{s['note']}", "kind": "organize", "note": s["note"],
                "summary": s["note"], "detail": "Suggested tags & related links", "items": items,
                "whole_only": False,
            })

    # memory — one approval per consolidation file; items = each proposed fact
    if vault:
        for p in consolidation.list_proposals(vault):
            items = [{"itemkind": "fact", "value": f, "label": f} for f in p["facts"]]
            out.append({
                "id": f"memory:{p['file']}", "kind": "memory", "note": p["path"],
                "summary": f"{len(items)} proposed fact(s)", "detail": "Durable facts to remember",
                "items": items, "whole_only": False,
            })

    # goal — one approval per goal awaiting the go-ahead; steps shown read-only
    for g in goals_store.load_goals():
        if g.get("status") == "proposed":
            steps = [{"itemkind": "step", "value": str(s["id"]), "label": s["task"]}
                     for s in g.get("subtasks", [])]
            out.append({
                "id": f"goal:{g['slug']}", "kind": "goal", "note": f"AI/System/Goals/{g['slug']}.md",
                "summary": g["description"], "detail": g.get("estimate", "") or f"{len(steps)} step(s)",
                "items": steps, "whole_only": True,
            })

    return out


def _split(approval_id: str) -> tuple[str, str]:
    kind, _, ref = approval_id.partition(":")
    return kind, ref


def apply_approval(vault, approval_id: str, item: dict | None = None) -> dict:
    """Commit an approval — a single item when `item` is given, else the whole thing."""
    kind, ref = _split(approval_id)

    if kind == "organize":
        if item:
            return {"applied": organize.apply_one(vault, ref, item["itemkind"], item["value"])}
        s = next((x for x in organize.load_pending() if x["note"] == ref), None)
        if not s:
            return {"applied": False, "reason": "not found"}
        return {"applied": organize.apply_suggestion(vault, ref, s.get("tags"), s.get("related"))}

    if kind == "memory":
        if item:
            r = consolidation.apply_fact(vault, ref, item["value"])
            return {"applied": bool(r.get("applied"))}
        p = next((x for x in consolidation.list_proposals(vault) if x["file"] == ref), None)
        facts = p["facts"] if p else []
        for f in facts:
            from assistant_core import feedback
            feedback.record("fact", f, True)
        r = consolidation.apply_proposal(vault, ref, facts)
        return {"applied": bool(r.get("applied"))}

    if kind == "goal":
        g = goals_store.set_status(ref, "running")
        return {"applied": bool(g)}

    return {"applied": False, "reason": f"unknown kind {kind}"}


def reject_approval(vault, approval_id: str, item: dict | None = None) -> dict:
    """Dismiss an approval — a single item when `item` is given, else the whole thing.
    Records negative feedback so future suggestions learn from it."""
    kind, ref = _split(approval_id)

    if kind == "organize":
        if item:
            organize.reject_one(ref, item["itemkind"], item["value"])
        else:
            organize.reject_all(ref)
        return {"rejected": True}

    if kind == "memory":
        if item:
            consolidation.reject_fact(vault, ref, item["value"])
        else:
            p = next((x for x in consolidation.list_proposals(vault) if x["file"] == ref), None)
            for f in (p["facts"] if p else []):
                consolidation.reject_fact(vault, ref, f)
        return {"rejected": True}

    if kind == "goal":
        goals_store.set_status(ref, "cancelled")
        return {"rejected": True}

    return {"rejected": False, "reason": f"unknown kind {kind}"}
