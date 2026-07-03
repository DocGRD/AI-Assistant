"""
Graph build job — Milestone 18, Slices 1/3 driver.

Ties extraction to the store: read a note, detect privacy, extract triples, merge them
into the entity graph. `build_graph_for_note` powers the on-demand `vault:graph <note>`;
`build_graph` is the incremental nightly/one-shot pass — it hashes notes so only changed
ones are re-processed and caps how many it does per run to keep the LLM cost bounded.
Real user notes only (the derived `AI/` trees are skipped).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from assistant_core.graph.extractor import extract_triples
from assistant_core.graph.store import merge_triples
from assistant_core.watcher.frontmatter_parser import FrontmatterParser

logger = logging.getLogger("assistant")

STATE_FILE = "AI/Graph/.graph-state.json"
# Derived / system trees we never extract a graph FROM.
_SKIP_PREFIXES = ("AI/Graph", "AI/System", "AI/Memory", "AI/Chat", "AI/Derived", ".")


def _note_private(fm: dict) -> bool:
    return str(fm.get("private", "")).lower() in ("true", "yes", "1")


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def build_graph_for_note(vault, router, rel_path: str) -> dict:
    rel_path = rel_path.replace("\\", "/")
    note = Path(vault) / rel_path
    if not note.is_file():
        return {"note": rel_path, "error": "not found", "triples": 0, "entities": 0}
    content = note.read_text(encoding="utf-8")
    fm, body = FrontmatterParser.extract(content)
    private = _note_private(fm)
    triples = extract_triples(router, body, private=private)
    rep = merge_triples(vault, triples, rel_path, private=private) if triples else {"entities": 0, "relations": 0}
    return {"note": rel_path, "triples": len(triples), **rep}


def _skip(rel: str) -> bool:
    return any(rel.startswith(p) for p in _SKIP_PREFIXES)


def _read_state(vault) -> dict:
    try:
        return json.loads((Path(vault) / STATE_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(vault, state: dict) -> None:
    try:
        p = Path(vault) / STATE_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state), encoding="utf-8")
    except Exception as exc:
        logger.debug(f"[Graph] could not persist state: {exc}")


def build_graph(vault, router, limit: int = 50) -> dict:
    """Incremental pass: extract from up to `limit` changed real-user notes. Idempotent
    via a per-note content hash. Returns {processed, entities, relations}."""
    vault = Path(vault)
    state = _read_state(vault)
    report = {"processed": [], "entities": 0, "relations": 0}
    for note in sorted(vault.rglob("*.md")):
        rel = str(note.relative_to(vault)).replace("\\", "/")
        if _skip(rel):
            continue
        try:
            content = note.read_text(encoding="utf-8")
        except Exception:
            continue
        h = _hash(content)
        if state.get(rel) == h:
            continue                          # unchanged since last pass
        rep = build_graph_for_note(vault, router, rel)
        state[rel] = h
        report["processed"].append(rel)
        report["entities"] += rep.get("entities", 0)
        report["relations"] += rep.get("relations", 0)
        if len(report["processed"]) >= limit:
            break
    _write_state(vault, state)
    logger.info(f"[Graph] processed {len(report['processed'])} note(s), "
                f"+{report['relations']} relation(s).")
    return report
