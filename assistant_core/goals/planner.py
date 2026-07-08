"""
Goal planner — Milestone 35.

One low-temperature LLM call decomposes a high-level goal into concrete, ordered steps
each doable by the agent in a single turn (it has the full `vault:` command set from
M33 — web research, ingest, create, etc.), plus a rough resource/time estimate. The plan
is returned for the user to approve before anything runs.
"""

import logging
import re

logger = logging.getLogger("assistant")

_PLAN_SYSTEM = (
    "You are a planner for an autonomous Obsidian vault assistant. Break the user's goal into "
    "3-12 concrete, ordered steps. Each step is ONE clear instruction the assistant can do in a "
    "single turn using its tools (e.g. 'Use vault:webresearch to find X and save it', "
    "'Create a note at AI/Library/<name>.md summarising Y', 'Search the vault for Z'). "
    "Be specific and realistic; do not invent facts. "
    "Respond EXACTLY in this format and nothing else:\n"
    "STEPS:\n1. <step>\n2. <step>\n...\nESTIMATE: <one short line: approx how many steps / model "
    "calls / notes, and that it runs gradually in the background>"
)


# M39 (C2) — typed goal pipelines. Each template turns one argument into a proven
# pipeline of real vault: commands, so common goals expand deterministically (no model,
# no plan drift) into steps the worker can run one-per-tick.
TEMPLATES: dict[str, tuple[str, "callable"]] = {
    "research": (
        "Research a topic from the web into the vault",
        lambda a: [
            f'Use vault:webresearch to research "{a}" and save the cited findings',
            f'Use vault:ingest to index the saved research on "{a}"',
            f'Use vault:graph to extract key entities and relationships about "{a}"',
            f'Use vault:cards to create study cards about "{a}"',
        ],
    ),
    "digest": (
        "Digest a document already in the vault",
        lambda a: [
            f"Use vault:ingest to import and index {a}",
            f"Use vault:graph to extract entities from {a}",
            f"Use vault:guide to build a study guide for {a}",
            f"Use vault:cards to create study cards from {a}",
            f"Use vault:review to schedule the new cards",
        ],
    ),
    "study": (
        "Study a scripture passage or note",
        lambda a: [
            f"Use vault:passage to load {a}",
            f"Use vault:cards to make memorization cards for {a}",
            f"Use vault:review to schedule {a} for spaced repetition",
        ],
    ),
}


def plan_from_template(name: str, arg: str) -> dict | None:
    """Expand a named template into {'subtasks', 'estimate', 'template'}, or None if unknown."""
    entry = TEMPLATES.get((name or "").lower())
    if not entry or not (arg or "").strip():
        return None
    _desc, fn = entry
    subs = fn(arg.strip())
    return {"subtasks": subs, "template": name.lower(),
            "estimate": f"~{len(subs)} steps · a few model calls · runs in the background"}


def detect_template(description: str) -> str | None:
    """Pick a template when the goal clearly matches one (first word), else None."""
    first = (description or "").strip().split(None, 1)[0].lower()
    return first if first in TEMPLATES else None


def plan_goal(description: str, router, private: bool = False) -> dict:
    """Return {'subtasks': [str], 'estimate': str}. Empty subtasks if planning failed."""
    from assistant_core.providers.base_provider import Message
    try:
        reply, _ = router.generate(
            [Message(role="user", content=f"Goal: {description}")],
            system_prompt=_PLAN_SYSTEM, task="qa", private=private, allow_webui=False,
        )
    except Exception as exc:
        logger.warning(f"[Planner] failed: {exc}")
        return {"subtasks": [], "estimate": ""}
    return parse_plan(reply or "")


def parse_plan(text: str) -> dict:
    subtasks: list[str] = []
    estimate = ""
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^\d+[.)]\s+(.*\S)", line)
        if m:
            subtasks.append(m.group(1).strip())
        elif line.lower().startswith("estimate:"):
            estimate = line.split(":", 1)[1].strip()
    return {"subtasks": subtasks[:12], "estimate": estimate}
