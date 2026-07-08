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
