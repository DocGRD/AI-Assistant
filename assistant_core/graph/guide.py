"""
Graph-aware retrieval / Guides — Milestone 18 (completes the deferred slice).

Turns the entity graph into an answer engine: map a topic to an entity, pull its
connected cluster (`read_subgraph`) and the source notes behind those entities, then
assemble a **cited** overview in one non-agentic call — the "give me everything about X"
Guide. Private entities are excluded. No agent loop, so it can't loop or fabricate links.
"""

from __future__ import annotations

import logging
from pathlib import Path

from assistant_core.graph.store import ENTITIES_DIR, read_subgraph, _load_entity, _all_entities, _cosine

logger = logging.getLogger("assistant")


def find_entity(vault, topic: str, embedder=None) -> str | None:
    """Best entity for a topic: exact name → substring → embedder-nearest (≥0.5)."""
    names = _all_entities(vault)
    if not names:
        return None
    t = (topic or "").strip().lower()
    if not t:
        return None
    for n in names:
        if n.lower() == t:
            return n
    subs = [n for n in names if t in n.lower() or n.lower() in t]
    if subs:
        return sorted(subs, key=len)[0]
    if embedder is not None:
        try:
            qv = embedder.embed_one(topic)
            vecs = embedder.embed(names)
            best = max(range(len(names)), key=lambda i: _cosine(qv, vecs[i]))
            if _cosine(qv, vecs[best]) >= 0.5:
                return names[best]
        except Exception as exc:
            logger.warning(f"[Graph] entity embed match failed: {exc}")
    return None


def _synthesise_guide(router, topic, entity, relations, excerpts) -> str:
    if router is None:
        return ""
    from assistant_core.providers.base_provider import Message
    rel_text = "\n".join(f"- {r}" for r in relations) or "(no relations recorded)"
    src_text = "\n\n".join(f"### [[{stem}]]\n{txt}" for stem, txt in excerpts) or "(no source notes)"
    msg = (f"Entity: {entity}\n\nGraph relations:\n{rel_text}\n\nSource-note excerpts:\n{src_text}")
    sys = ("Assemble a concise, well-organised guide to the entity, drawing ONLY on the graph "
           "relations and source excerpts provided. Cite source notes inline as [[note name]]. "
           "Do not invent facts, relations, or note names. End with a short 'Related' line listing "
           "the connected entities.")
    try:
        reply, _ = router.generate(messages=[Message(role="user", content=msg[:9000])],
                                   system_prompt=sys, max_tokens=800, temperature=0.3,
                                   private=False, allow_webui_on_private=False)
        return (reply or "").strip()
    except Exception as exc:
        logger.warning(f"[Graph] guide synthesis failed: {exc}")
        return ""


def build_guide(vault, router, topic: str, rag=None, depth: int = 1,
                include_private: bool = False) -> dict:
    """Assemble a cited guide for `topic` from the graph + its source notes. Private
    entities are included only when `include_private` (config `graph_include_private`)."""
    report = {"topic": topic, "entity": None, "guide": "", "sources": [], "error": None}
    embedder = rag.embedder if (rag and getattr(rag, "enabled", False)) else None
    entity = find_entity(vault, topic, embedder)
    if not entity:
        report["error"] = (f"no graph entity matches '{topic}'. "
                           "Build the graph first with vault:graph <note> or --build-graph.")
        return report
    report["entity"] = entity

    sg = read_subgraph(vault, entity, depth=depth, include_private=include_private)
    relations = [f"{e['source']} {e['rel']} {e['target']}" for e in sg["edges"]]
    src_stems: set[str] = set()
    for n in sg["nodes"]:
        src_stems.update(n.get("sources", []))

    excerpts = []
    for stem in sorted(src_stems)[:8]:
        matches = list(Path(vault).rglob(f"{stem}.md"))
        if matches:
            try:
                excerpts.append((stem, matches[0].read_text(encoding="utf-8")[:1500]))
            except Exception:
                pass

    report["sources"] = sorted(src_stems)
    report["guide"] = _synthesise_guide(router, topic, entity, relations, excerpts)
    return report
