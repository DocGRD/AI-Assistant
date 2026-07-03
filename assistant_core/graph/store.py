"""
Markdown graph store — Milestone 18, Slice 2.

Materialises extracted triples as linked Markdown **entity notes** under
`AI/Graph/Entities/`. Each entity is one note with frontmatter (`ai-graph: entity`,
`type`, `private`) and two sections: `## Relations` (labelled `[[wikilinks]]` to other
entities) and `## Source notes` (back-links to the notes it came from). Obsidian's own
graph view renders the result for free.

Derived, namespaced, and rebuildable (like the RAG index / OCR sidecars): merges are
append-only and idempotent, so re-running the nightly extraction never duplicates a
relation. Privacy is sticky — once any private source contributes to an entity it stays
`private: true` and is hidden from non-private subgraph queries.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from assistant_core.watcher.frontmatter_parser import FrontmatterParser

logger = logging.getLogger("assistant")

ENTITIES_DIR = "AI/Graph/Entities"
_UNSAFE_FILE = re.compile(r"[\\/:*?\"<>|]")
_REL_LINE = re.compile(r"^\s*-\s+(.+?)\s+\[\[([^\]]+)\]\]\s*$")
_SRC_LINE = re.compile(r"^\s*-\s+\[\[([^\]]+)\]\]\s*$")


def entity_filename(name: str) -> str:
    return _UNSAFE_FILE.sub("", name).strip() or "Unnamed"


def _entity_path(vault, name: str) -> Path:
    return Path(vault) / ENTITIES_DIR / f"{entity_filename(name)}.md"


def _load_entity(vault, name: str) -> dict:
    """Parse an entity note into {name, type, private, aliases, relations:set, sources:set}."""
    path = _entity_path(vault, name)
    data = {"name": name, "type": "concept", "private": False,
            "aliases": set(), "relations": set(), "sources": set()}
    if not path.exists():
        return data
    fm, body = FrontmatterParser.extract(path.read_text(encoding="utf-8"))
    data["type"] = str(fm.get("type", "concept")).strip() or "concept"
    data["private"] = str(fm.get("private", "")).lower() in ("true", "yes", "1")
    # The frontmatter parser returns everything as strings, so an inline list like
    # "aliases: [RMH, Foo]" arrives as the string "[RMH, Foo]" — split it ourselves.
    aliases = fm.get("aliases", "")
    if isinstance(aliases, list):
        parts = [str(a).strip() for a in aliases]
    else:
        parts = [a.strip() for a in str(aliases).strip().strip("[]").split(",")]
    data["aliases"] = {a for a in parts if a}
    section = None
    for line in body.splitlines():
        h = line.strip().lower()
        if h.startswith("## relations"):
            section = "rel"; continue
        if h.startswith("## source"):
            section = "src"; continue
        if line.startswith("#"):
            section = None; continue
        if section == "rel":
            m = _REL_LINE.match(line)
            if m:
                data["relations"].add((m.group(1).strip(), m.group(2).strip()))
        elif section == "src":
            m = _SRC_LINE.match(line)
            if m:
                data["sources"].add(m.group(1).strip())
    return data


def _write_entity(vault, data: dict) -> None:
    path = _entity_path(vault, data["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    alias_line = ("aliases: [" + ", ".join(sorted(data.get("aliases", set()))) + "]"
                  if data.get("aliases") else "aliases: []")
    lines = [
        "---", "ai-graph: entity", f"type: {data['type']}",
        f"private: {'true' if data['private'] else 'false'}", alias_line, "---", "",
        f"# {data['name']}", "", "## Relations", "",
    ]
    lines += [f"- {rel} [[{tgt}]]" for rel, tgt in sorted(data["relations"])] or ["_(none yet)_"]
    lines += ["", "## Source notes", ""]
    lines += [f"- [[{s}]]" for s in sorted(data["sources"])] or ["_(none yet)_"]
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def merge_triples(vault, triples, source_note: str, private: bool = False) -> dict:
    """Merge triples into entity notes (append-only, idempotent). `source_note` is the
    vault-relative path the triples came from. Returns {entities, relations}."""
    src_name = Path(source_note).stem if source_note else ""
    touched: set[str] = set()
    rel_count = 0
    for subj, rel, obj in triples:
        s = _load_entity(vault, subj)
        if (rel, obj) not in s["relations"]:
            s["relations"].add((rel, obj)); rel_count += 1
        if src_name:
            s["sources"].add(src_name)
        if private:
            s["private"] = True
        _write_entity(vault, s)
        touched.add(subj)

        # Ensure the object exists as a node too (so links resolve + it's reachable).
        o = _load_entity(vault, obj)
        if src_name:
            o["sources"].add(src_name)
        if private:
            o["private"] = True
        _write_entity(vault, o)
        touched.add(obj)
    return {"entities": len(touched), "relations": rel_count}


def _all_entities(vault) -> list[str]:
    ent_dir = Path(vault) / ENTITIES_DIR
    if not ent_dir.is_dir():
        return []
    return sorted(p.stem for p in ent_dir.glob("*.md") if not p.stem.startswith("digest"))


def _cosine(a, b) -> float:
    import numpy as np
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a.dot(b) / (na * nb)) if na and nb else 0.0


def suggest_aliases(vault, embedder=None, threshold: float = 0.9) -> list[tuple[str, str, float]]:
    """Candidate entity merges (near-duplicate names). Uses the embedder when available,
    plus cheap string signals (substring / case-insensitive equality). Propose/commit —
    this only *suggests*; `merge_entities` applies. Returns (canonical, alias, score),
    canonical = the longer/more-specific name."""
    names = _all_entities(vault)
    pairs: dict[tuple[str, str], float] = {}

    def add(a, b, score):
        canon, alias = (a, b) if len(a) >= len(b) else (b, a)
        key = (canon, alias)
        if canon != alias and score >= threshold and score > pairs.get(key, 0):
            pairs[key] = score

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            al, bl = a.lower(), b.lower()
            if al == bl or al in bl or bl in al:
                add(a, b, 0.97)

    if embedder is not None and len(names) > 1:
        try:
            vecs = embedder.embed(names)
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    add(names[i], names[j], _cosine(vecs[i], vecs[j]))
        except Exception as exc:
            logger.warning(f"[Graph] alias embedding failed: {exc}")

    out = [(c, a, round(s, 3)) for (c, a), s in pairs.items()]
    return sorted(out, key=lambda t: -t[2])


def merge_entities(vault, canonical: str, alias: str) -> bool:
    """Merge `alias` into `canonical`: union relations/sources/aliases, rewrite every
    `[[alias]]` relation in other entity notes to `[[canonical]]`, then delete the alias
    note. Reversible via a graph rebuild. Returns False if either is missing/identical."""
    if entity_filename(canonical) == entity_filename(alias):
        return False
    alias_path = _entity_path(vault, alias)
    if not alias_path.exists():
        return False

    c = _load_entity(vault, canonical)
    a = _load_entity(vault, alias)
    c["relations"] |= {(rel, canonical if tgt == alias else tgt) for rel, tgt in a["relations"]}
    c["sources"]   |= a["sources"]
    c["aliases"]   |= a["aliases"] | {alias}
    c["private"]    = c["private"] or a["private"]
    c["relations"]  = {(r, t) for r, t in c["relations"] if t != canonical}   # drop self-loops
    _write_entity(vault, c)

    # Repoint incoming links from other entity notes.
    for name in _all_entities(vault):
        if name in (canonical, alias):
            continue
        d = _load_entity(vault, name)
        if any(tgt == alias for _, tgt in d["relations"]):
            d["relations"] = {(rel, canonical if tgt == alias else tgt) for rel, tgt in d["relations"]}
            _write_entity(vault, d)

    alias_path.unlink()
    logger.info(f"[Graph] merged entity '{alias}' → '{canonical}'")
    return True


def list_entities(vault, include_private: bool = False) -> list[dict]:
    """All entities as {id, degree, type}, most-connected first — so the plugin can offer
    starting points without the user knowing node names. Degree = outgoing + incoming
    relations. Private entities are excluded unless `include_private`."""
    names = _all_entities(vault)
    deg = {n: 0 for n in names}
    info = {}
    for n in names:
        d = _load_entity(vault, n)
        info[n] = d
        deg[n] += len(d["relations"])
        for _, tgt in d["relations"]:
            if tgt in deg:
                deg[tgt] += 1
    out = [{"id": n, "degree": deg[n], "type": info[n]["type"]}
           for n in names if include_private or not info[n]["private"]]
    return sorted(out, key=lambda e: (-e["degree"], e["id"].lower()))


def read_subgraph(vault, node: str, depth: int = 1, include_private: bool = False) -> dict:
    """BFS the entity graph from `node` out to `depth`. Returns {nodes, edges}. Private
    nodes are hidden unless `include_private`. Node count is caller-capped upstream."""
    ent_dir = Path(vault) / ENTITIES_DIR
    if not ent_dir.is_dir():
        return {"nodes": [], "edges": []}

    def visible(name: str) -> bool:
        d = _load_entity(vault, name)
        return include_private or not d["private"]

    start = entity_filename(node)
    if not (ent_dir / f"{start}.md").exists() or not visible(node):
        return {"nodes": [], "edges": []}

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    frontier = [(node, 0)]
    seen = {entity_filename(node)}
    while frontier:
        name, d = frontier.pop(0)
        data = _load_entity(vault, name)
        nodes[entity_filename(name)] = {"id": name, "type": data["type"],
                                        "sources": sorted(data["sources"])}
        if d >= depth:
            continue
        for rel, tgt in sorted(data["relations"]):
            if not visible(tgt):
                continue
            edges.append({"source": name, "target": tgt, "rel": rel})
            key = entity_filename(tgt)
            if key not in seen:
                seen.add(key)
                frontier.append((tgt, d + 1))
    return {"nodes": list(nodes.values()), "edges": edges}
