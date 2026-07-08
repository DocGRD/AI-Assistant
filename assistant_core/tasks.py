"""
Action layer — Milestone 39 (D-action-layer).

Notes often *contain* work — to-dos, decisions, follow-ups — but Loremaster only stored
them. `vault:actions <note>` pulls those out into a tracked checklist under `AI/Tasks/`
(propose-only; the source note is never touched) and the daily briefing surfaces the ones
still open. Extraction is deterministic first (checkboxes, TODO/ACTION markers, obligation
phrases); an optional single LLM pass can enrich it when a router is available.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("assistant")

TASKS_DIR = "AI/Tasks"

_CHECKBOX = re.compile(r"^\s*[-*]\s*\[\s\]\s*(.+\S)", re.MULTILINE)     # open checkboxes only
_MARKER = re.compile(r"^\s*(?:[-*]\s*)?(?:TODO|ACTION|FOLLOW[- ]?UP|NEXT STEP)\s*[:\-]\s*(.+\S)",
                     re.IGNORECASE | re.MULTILINE)
_OBLIGATION = re.compile(
    r"\b(?:I|we|you)\s+(?:need to|should|must|have to|ought to|will need to|plan to|"
    r"want to|intend to)\s+(.+?)(?:[.!?]|$)", re.IGNORECASE)


def extract_actions(text: str, router=None, private: bool = False) -> list[str]:
    """Action items found in `text`, deduped, order-preserving. Deterministic; the optional
    router adds an LLM pass only when nothing deterministic was found."""
    out: list[str] = []

    def _add(s: str) -> None:
        s = s.strip().rstrip(".").strip()
        if 3 <= len(s) <= 200 and s.lower() not in {o.lower() for o in out}:
            out.append(s)

    for m in _CHECKBOX.finditer(text):
        _add(m.group(1))
    for m in _MARKER.finditer(text):
        _add(m.group(1))
    for m in _OBLIGATION.finditer(text):
        verb = m.group(0).split(None, 1)
        _add((verb[1] if len(verb) > 1 else m.group(1)))

    if not out and router is not None:
        try:
            from assistant_core.providers.base_provider import Message
            q = ("List the concrete action items / to-dos in this note, one per line, "
                 "no commentary. If there are none, output nothing.\n\n" + text[:3000])
            reply, _ = router.generate([Message(role="user", content=q)],
                                       task="extract", private=private, allow_webui=False)
            for line in (reply or "").splitlines():
                s = line.strip(" -*0123456789.").strip()
                if s:
                    _add(s)
        except Exception as exc:
            logger.info(f"[tasks] LLM extraction skipped: {exc}")
    return out[:30]


def write_actions(vault, note_rel: str, router=None) -> tuple[str | None, int]:
    """Extract `note_rel`'s actions into a propose-only AI/Tasks/<stem>.md checklist.
    Returns (rel_path, count) — (None, 0) if the note is missing or has no actions."""
    src = Path(vault) / note_rel
    if not src.exists():
        return None, 0
    try:
        text = src.read_text(encoding="utf-8")
    except Exception:
        return None, 0
    private = bool(re.search(r"^private:\s*true", text, re.MULTILINE | re.IGNORECASE))
    actions = extract_actions(text, router, private=private)
    if not actions:
        return None, 0
    stem = Path(note_rel).stem
    lines = [f"# Actions — {stem}", "",
             f"*Extracted from [[{stem}]] by Loremaster. Propose-only — the source note was "
             f"not changed. Tick items here as you do them.*", ""]
    lines += [f"- [ ] {a}" for a in actions]
    rel = f"{TASKS_DIR}/{stem}.md"
    dest = Path(vault) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"[tasks] wrote {rel} ({len(actions)} action(s))")
    return rel, len(actions)


def open_actions(vault, limit: int = 10) -> list[str]:
    """Open (unchecked) action items across AI/Tasks/ — for the daily briefing."""
    tdir = Path(vault) / TASKS_DIR
    out: list[str] = []
    if not tdir.is_dir():
        return out
    for p in sorted(tdir.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in _CHECKBOX.finditer(text):
            out.append(f"{p.stem}: {m.group(1).strip()}")
            if len(out) >= limit:
                return out
    return out
