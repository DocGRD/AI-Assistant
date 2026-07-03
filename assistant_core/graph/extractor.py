"""
Entity/relation extraction — Milestone 18, Slice 1.

One conservative, forced-private LLM call turns a note into typed triples
`Subject | relation | Object`. Reuses the M17 dream-time discipline: private routing
(no-train providers only, no web handoff), a strict prompt, and a hard cap so the cost
is bounded. Parsing is pure and unit-tested; the model call is injectable via the router.

The triples feed `graph/store.py`, which materialises them as linked Markdown entity
notes under `AI/Graph/` — browsable in Obsidian's own graph view.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("assistant")

_MAX_TRIPLES = 12

EXTRACT_SYSTEM = (
    "Extract the key entities and their relationships from the note as triples, one per "
    "line, in the exact form:  Subject | relation | Object\n"
    "Rules: use canonical Title-Case entity names (people, places, concepts, projects, "
    "works); keep the relation 1-3 lowercase words (e.g. 'is a', 'uses', 'wrote', "
    "'part of'); include only clear, factual relationships actually stated or strongly "
    f"implied; at most {_MAX_TRIPLES}. If there are none, output exactly NONE. Output only "
    "the triple lines — no headings, no commentary."
)

# A safe entity name: letters/digits/spaces/hyphen, trimmed, not absurdly long.
_BAD = re.compile(r"[^\w \-'&/.]")


def _clean_entity(name: str) -> str:
    name = _BAD.sub("", name).strip().strip("-").strip()
    return " ".join(name.split())[:60]


def parse_triples(reply: str) -> list[tuple[str, str, str]]:
    """Parse `Subject | relation | Object` lines. Skips blanks/malformed; '' on NONE."""
    if reply.strip().upper().startswith("NONE"):
        return []
    out: list[tuple[str, str, str]] = []
    for line in reply.splitlines():
        if line.count("|") < 2:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        subj, rel, obj = _clean_entity(parts[0]), " ".join(parts[1].lower().split())[:30], _clean_entity(parts[2])
        if subj and rel and obj and subj.lower() != obj.lower():
            out.append((subj, rel, obj))
        if len(out) >= _MAX_TRIPLES:
            break
    return out


def extract_triples(router, note_text: str, private: bool = True) -> list[tuple[str, str, str]]:
    """One forced-private LLM call → triples for a note. Empty on failure/no router."""
    if router is None or not note_text.strip():
        return []
    from assistant_core.providers.base_provider import Message
    try:
        reply, _ = router.generate(
            messages=[Message(role="user", content=note_text[:8000])],
            system_prompt=EXTRACT_SYSTEM, max_tokens=400, temperature=0.2,
            private=True, allow_webui_on_private=False,
        )
    except Exception as exc:
        logger.warning(f"[Graph] extraction call failed: {exc}")
        return []
    return parse_triples(reply or "")
