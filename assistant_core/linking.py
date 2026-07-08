"""
Connective-tissue service — Milestone 36 (C4).

Before this, "notes related to X" was computed three different ways:
  - vector similarity        (rag.service.relevant_notes)
  - link/tag graph neighbours (rag.graph.LinkGraph)
  - auto-organize's own guess (proactive.organize._related_links)

`related()` is the single merge point. It blends the vector and graph signals, drops
anything the vault can't resolve (no fabricated `[[links]]`, ever) and anything the user
has repeatedly rejected for this note (feedback-aware), and returns ranked note stems.
Callers pass whichever signals they have — a bare `rag` still works, a `graph` adds
link/tag neighbours, neither returns nothing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from assistant_core.links import link_exists
from assistant_core import feedback

logger = logging.getLogger("assistant")


def related(vault, note_path: str, k: int = 5, rag=None, graph=None,
            config: dict | None = None) -> list[str]:
    """Ranked, validated, feedback-filtered related-note stems for `note_path`.

    Scoring: vector hits keep their similarity score (0–1); graph link-neighbours get a
    flat 0.5, shared-tag neighbours 0.35 (weaker). A note appearing in several signals
    sums them, so multiply-supported notes rise. Everything is validated against the real
    vault and screened against link feedback for this note.
    """
    config = config or {}
    scores: dict[str, float] = {}

    # 1) vector similarity — pull a few extra so filtering still leaves k
    if rag is not None and getattr(rag, "has_index", lambda: False)():
        try:
            for r in rag.relevant_notes(note_path, k=max(k * 2, 8)):
                p = r.get("path") if isinstance(r, dict) else r
                if p:
                    scores[Path(p).stem] = scores.get(Path(p).stem, 0.0) + float(
                        r.get("score", 0.5) if isinstance(r, dict) else 0.5)
        except Exception as exc:
            logger.debug(f"[Linking] vector signal failed: {exc}")

    # 2) graph neighbours (link hops + shared tags), if a LinkGraph was supplied
    if graph is not None:
        try:
            for n in graph.neighbors(note_path):
                scores[Path(n).stem] = scores.get(Path(n).stem, 0.0) + 0.5
            for n in graph.tag_neighbors(note_path):
                scores[Path(n).stem] = scores.get(Path(n).stem, 0.0) + 0.35
        except Exception as exc:
            logger.debug(f"[Linking] graph signal failed: {exc}")

    own_stem = Path(note_path).stem
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    out: list[str] = []
    for stem, _ in ranked:
        if stem == own_stem or stem in out:
            continue
        if not link_exists(stem, vault):                       # no fabricated links
            continue
        if feedback.suppressed("link", stem, scope=note_path):  # user rejected it here
            continue
        out.append(stem)
        if len(out) >= k:
            break
    return out
