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
    "You build a knowledge graph. From the note, list the key entities (people, places, concepts, "
    "books, works, projects, events) and how they relate — one relationship per line, in exactly "
    "the form:  Subject | relation | Object\n"
    "Rules: canonical Title-Case entity names; a 1-3 word lowercase relation (e.g. 'is a', 'wrote', "
    "'uses', 'part of', 'refers to'); include only relationships the note actually states or clearly "
    f"implies — do NOT invent facts; at most {_MAX_TRIPLES}. Extract every clear one you can find. "
    "Output ONLY the triple lines — no headings, no commentary. Only if there is truly nothing, "
    "output exactly NONE."
)

# A safe entity name: letters/digits/spaces/hyphen, trimmed, not absurdly long.
_BAD = re.compile(r"[^\w \-'&/.]")


def _clean_entity(name: str) -> str:
    name = _BAD.sub("", name).strip().strip("-").strip()
    name = " ".join(name.split())[:60]
    # Reject junk the model sometimes emits as an "entity": pure numbers, quantities and
    # fragments with no real name content (e.g. "100000", "13", "116-17") — these flooded the
    # graph with thousands of meaningless entity notes. Require at least one letter, which still
    # keeps legitimate digit-led names like "1 John" / "2 Samuel".
    if not re.search(r"[A-Za-z]", name):
        return ""
    return name


def _clean_for_extraction(text: str) -> str:
    """Strip markdown/provenance clutter to plain prose — small local models extract far better from
    clean text than from raw notes full of headings, `> Ingested from …` blockquotes, wikilinks,
    verse markers and HTML spans."""
    text = re.sub(r"<[^>]+>", " ", text)                          # HTML / Strong's spans
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)       # [[target|alias]] -> alias
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)               # [[wikilink]] -> text
    text = re.sub(r"^\s*>.*$", "", text, flags=re.MULTILINE)       # blockquotes (provenance etc.)
    text = re.sub(r"\^v\d+", " ", text)                          # verse anchors
    text = re.sub(r"[#*`_|]", " ", text)                          # markdown emphasis/headings/table pipes
    return re.sub(r"\s+", " ", text).strip()


def parse_triples(reply: str) -> list[tuple[str, str, str]]:
    """Parse `Subject | relation | Object` lines. Skips blanks/malformed; '' on NONE."""
    reply = re.sub(r"^```[a-z]*\s*|\s*```$", "", reply.strip())   # unwrap a ```code fence``` (small models add one)
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
    # Prefer a LOCAL model (Ollama on the box) for graph extraction so it never burns cloud free-tier
    # limits — extraction is a high-volume background task and a small local model is plenty for it.
    # Configurable via `graph_extraction_provider` (default "ollama"); if that provider isn't built
    # (Ollama absent / no dummy key), fall back to normal private routing. The router still falls
    # through to a cloud model if the local one errors mid-request.
    override = str((router.config or {}).get("graph_extraction_provider", "ollama") or "").lower()
    if override and override not in router.available_models:
        override = None
    clean = _clean_for_extraction(note_text)
    if len(clean) < 40:
        return []                                   # nothing substantive to extract
    try:
        reply, used = router.generate(
            messages=[Message(role="user", content=clean[:8000])],
            system_prompt=EXTRACT_SYSTEM, max_tokens=400, temperature=0.2,
            private=True, allow_webui_on_private=False,
            provider_override=override or None,
        )
    except Exception as exc:
        logger.warning(f"[Graph] extraction call failed: {exc}")
        return []
    return parse_triples(reply or "")
