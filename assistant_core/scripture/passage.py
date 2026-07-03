"""
Passage Guide — Milestone 24, Slices 2-3.

Given a Bible reference, find every note that touches that passage (verse-range overlap,
not just exact string match) and assemble a cited overview — the notes-first analog of a
"passage guide" in modern Bible study software. One non-agentic synthesis call; no loop.
"""

from __future__ import annotations

import logging
from pathlib import Path

from assistant_core.scripture.refs import parse_refs_struct, refs_overlap, normalize_ref

logger = logging.getLogger("assistant")

# Derived/system trees we don't scan for passage notes.
_SKIP = ("AI/System", "AI/Graph", "AI/Memory", "AI/Chat", "AI/Derived", "AI/Tests", ".")


def find_passage_notes(vault, target_ref: str, limit: int = 12) -> list[dict]:
    """Notes whose scripture references overlap `target_ref`. Returns [{path, refs}]."""
    target = parse_refs_struct(target_ref)
    if not target:
        return []
    t = target[0]
    out = []
    vault = Path(vault)
    for note in sorted(vault.rglob("*.md")):
        rel = str(note.relative_to(vault)).replace("\\", "/")
        if any(rel.startswith(p) for p in _SKIP):
            continue
        try:
            content = note.read_text(encoding="utf-8")
        except Exception:
            continue
        matched = sorted({r["ref"] for r in parse_refs_struct(content) if refs_overlap(t, r)})
        if matched:
            out.append({"path": rel, "refs": matched})
        if len(out) >= limit:
            break
    return out


def build_passage_guide(vault, router, ref: str, rag=None) -> dict:
    """Assemble a cited overview of everything the vault says about a passage."""
    report = {"ref": None, "guide": "", "notes": [], "error": None}
    canon = normalize_ref(ref)
    if not canon:
        report["error"] = f"'{ref}' is not a recognised scripture reference (e.g. '1 John 2:18-20')."
        return report
    report["ref"] = canon

    notes = find_passage_notes(vault, canon)
    report["notes"] = [n["path"] for n in notes]
    if not notes:
        report["error"] = f"no notes reference {canon} yet."
        return report

    excerpts = []
    for n in notes[:8]:
        try:
            excerpts.append((n["path"], (Path(vault) / n["path"]).read_text(encoding="utf-8")[:1200]))
        except Exception:
            pass

    if router is None:
        report["guide"] = "\n".join(f"- [[{Path(p).stem}]]" for p in report["notes"])
        return report

    from assistant_core.providers.base_provider import Message
    body = "\n\n".join(f"### [[{Path(p).stem}]]\n{txt}" for p, txt in excerpts)
    sys = (f"Assemble a concise, organised overview of what these notes say about {canon}. Draw ONLY "
           "on the excerpts; cite each note as [[note name]]. Do not invent content or references.")
    try:
        reply, _ = router.generate(messages=[Message(role="user", content=body[:9000])],
                                   system_prompt=sys, max_tokens=800, temperature=0.3,
                                   private=False, allow_webui_on_private=False)
        report["guide"] = (reply or "").strip()
    except Exception as exc:
        logger.warning(f"[Scripture] passage guide synthesis failed: {exc}")
        report["guide"] = "\n".join(f"- [[{Path(p).stem}]]" for p in report["notes"])
    return report
