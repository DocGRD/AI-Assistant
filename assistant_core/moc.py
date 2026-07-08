"""
Map-of-Content generation — Milestone 38 (D-synthesis).

`vault:moc <topic>` assembles a **Map of Content**: an index note that gathers the vault's
notes on a topic into one navigable hub. It blends two signals — deterministic term-overlap
(`provenance.find_sources`, always available) and semantic similarity (the RAG index, when
present) — validates every link against the real vault, and writes a **propose-only** note
under `AI/Proposed/` (nothing is moved or overwritten; the user keeps/moves it).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from assistant_core.provenance import find_sources
from assistant_core.links import link_exists

logger = logging.getLogger("assistant")

PROPOSED_DIR = "AI/Proposed"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "moc"


def _candidates(vault, topic: str, rag=None, k: int = 25) -> list[str]:
    """Note stems related to `topic` (semantic + term-overlap), validated, deduped."""
    stems: list[str] = []

    if rag is not None and getattr(rag, "has_index", lambda: False)():
        try:
            import numpy as np  # noqa: F401
            qvec = rag.embedder.embed_one(topic)
            with rag._lock:
                for _score, m in rag.store.search(qvec, k=k * 2):
                    p = m.get("note_path")
                    if p:
                        st = Path(p).stem
                        if st not in stems:
                            stems.append(st)
        except Exception as exc:
            logger.debug(f"[moc] semantic pass skipped: {exc}")

    for s in find_sources(vault, topic, limit=k).get("sources", []):
        st = Path(s["path"]).stem
        if st not in stems:
            stems.append(st)

    return [s for s in stems if link_exists(s, vault)][:k]


def build_moc(vault, topic: str, rag=None, router=None, now: datetime | None = None) -> str | None:
    """Write a propose-only MOC note for `topic`. Returns the vault-relative path, or None
    if nothing related was found."""
    now = now or datetime.now()
    stems = _candidates(vault, topic, rag)
    if not stems:
        return None

    lines = [f"# MOC — {topic}", "",
             f"*A Map of Content for **{topic}**, proposed by Loremaster on "
             f"{now.strftime('%Y-%m-%d')}. Review, rename, and move it wherever you like — "
             f"nothing else was changed.*", "",
             f"## Notes on {topic} ({len(stems)})", ""]
    lines += [f"- [[{s}]]" for s in stems]
    lines += ["", "---", f"*Proposed by Loremaster — `vault:moc {topic}`.*"]

    rel = f"{PROPOSED_DIR}/moc-{_slug(topic)}.md"
    dest = Path(vault) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"[moc] wrote {rel} ({len(stems)} notes)")
    return rel
