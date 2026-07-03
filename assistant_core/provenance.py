"""
Provenance & citations — Milestone 25.

A trust layer: given a claim or a generated answer, find which vault notes actually
support it and flag it when nothing does. Deterministic (term overlap, no LLM) so it can
audit the assistant's own output. The consolidation facts, graph relations, web research,
and ingested documents already record their sources; this adds the audit tool on top.

`vault:sources <claim>` → the supporting notes (most-supporting first), and whether the
claim is sourced at all.
"""

from __future__ import annotations

import re
from math import ceil
from pathlib import Path

from assistant_core.watcher.frontmatter_parser import FrontmatterParser

_SKIP = ("AI/Memory/Episodes", "AI/Chat", ".obsidian", ".git", ".trash", ".venv")
# Prefix-excluded trees: test scaffolding is not a knowledge source.
_SKIP_PREFIX = ("AI/Memory/Episodes", "AI/Tests")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")   # significant words (4+ letters)
_STOP = {"this", "that", "with", "from", "have", "will", "your", "they", "them", "then",
         "than", "when", "what", "which", "there", "their", "about", "would", "could",
         "should", "these", "those", "been", "were", "into", "also", "such", "some", "note"}


def _terms(text: str) -> list[str]:
    seen, out = set(), []
    for w in _WORD_RE.findall((text or "").lower()):
        if w not in _STOP and w not in seen:
            seen.add(w); out.append(w)
    return out


def find_sources(vault, claim: str, limit: int = 8) -> dict:
    """Notes supporting `claim`, scored by how many of its key terms they contain.
    'sourced' is True when at least one note contains a majority of the terms."""
    terms = _terms(claim)
    report = {"claim": claim, "terms": terms, "sources": [], "sourced": False}
    if not terms:
        return report
    need = max(2, ceil(len(terms) / 2))
    vault = Path(vault)
    scored = []
    for note in vault.rglob("*.md"):
        rel = str(note.relative_to(vault)).replace("\\", "/")
        if any(x in note.parts for x in _SKIP) or rel.startswith(_SKIP_PREFIX):
            continue
        try:
            content = note.read_text(encoding="utf-8").lower()
        except Exception:
            continue
        hits = sum(1 for t in terms if t in content)
        if hits:
            scored.append({"path": rel, "matched": hits, "of": len(terms)})
    scored.sort(key=lambda r: -r["matched"])
    report["sources"] = scored[:limit]
    report["sourced"] = any(s["matched"] >= need for s in scored)
    return report
