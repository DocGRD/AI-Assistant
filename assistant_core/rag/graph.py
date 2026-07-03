"""
Structural link/tag graph — Milestone 16.

Built (cheaply, in memory) from the per-note graph info the indexer records in the
vector store (`store.note_meta` → `{rel_path: {"links": [...], "tags": [...]}}`).
The graph is what makes retrieval *hybrid*: after the vector search, the retriever
expands and reranks candidates by 1-hop `[[link]]` proximity and shared `#tags`.

Nothing is persisted here — it's derived from the (rebuildable) index, so it's free
and always in sync. Private notes are already excluded upstream (the indexer records
no links/tags for them), so the graph never reaches private content.
"""

from __future__ import annotations


def _norm(path: str) -> str:
    return path.replace("\\", "/").lower().removesuffix(".md")


class LinkGraph:
    def __init__(self, note_meta: dict[str, dict], known_notes):
        self.note_meta = note_meta or {}

        # Resolution maps: a `[[wikilink]]` target → an actual indexed note path.
        self._by_path: dict[str, str] = {}
        self._by_base: dict[str, str] = {}
        for rel in known_notes:
            n = _norm(rel)
            self._by_path.setdefault(n, rel)
            self._by_base.setdefault(n.rsplit("/", 1)[-1], rel)

        # Undirected 1-hop adjacency from resolved outlinks (+ their reverses).
        self._adj: dict[str, set[str]] = {}
        # Tag → notes that carry it.
        self._by_tag: dict[str, set[str]] = {}
        for rel, info in self.note_meta.items():
            for target in (info or {}).get("links", []):
                dest = self.resolve(target)
                if dest and dest != rel:
                    self._adj.setdefault(rel, set()).add(dest)
                    self._adj.setdefault(dest, set()).add(rel)   # undirected
            for tag in (info or {}).get("tags", []):
                self._by_tag.setdefault(tag, set()).add(rel)

    @property
    def is_empty(self) -> bool:
        return not self._adj and not self._by_tag

    def resolve(self, target: str) -> str | None:
        """Resolve a normalised link target to an indexed note path (or None)."""
        t = _norm(target)
        return self._by_path.get(t) or self._by_base.get(t.rsplit("/", 1)[-1])

    def neighbors(self, note_path: str) -> set[str]:
        """Notes one `[[link]]` hop away (in either direction)."""
        return set(self._adj.get(note_path, ()))

    def neighbors_within(self, note_path: str, hops: int = 1) -> set[str]:
        """All notes within `hops` link hops (BFS), excluding the note itself."""
        hops = max(1, int(hops))
        seen: set[str] = set()
        frontier = {note_path}
        for _ in range(hops):
            nxt: set[str] = set()
            for n in frontier:
                nxt |= self._adj.get(n, set())
            nxt -= seen
            nxt.discard(note_path)
            if not nxt:
                break
            seen |= nxt
            frontier = nxt
        return seen

    def tag_neighbors(self, note_path: str) -> set[str]:
        """Notes sharing at least one tag with `note_path` (excluding itself)."""
        out: set[str] = set()
        for tag in (self.note_meta.get(note_path) or {}).get("tags", []):
            out |= self._by_tag.get(tag, set())
        out.discard(note_path)
        return out
