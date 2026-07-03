"""
Retriever — Milestone 11, hybrid (graph-aware) since Milestone 16.

Embeds a query locally and finds the most relevant chunks. Vector similarity is
the base signal; when the index carries a link/tag graph (M16), the retriever
*expands* the candidate set with 1-hop `[[link]]` neighbours and shared-`#tag`
notes and *reranks* by `vector + link_proximity + tag_overlap`. With no graph in
the index it degrades to exactly the M11 vector ranking.

Each hit carries its `private` flag (so the QA layer can force private routing
when any source is private) and a `source` tag ("vector" or "graph") for the UI.
"""

from dataclasses import dataclass

from assistant_core.rag.graph import LinkGraph

# Hybrid defaults — vector dominates; the graph only nudges. Override per
# component via settings.json `hybrid_weights`. Set `hybrid_retrieval: false` to
# disable entirely (pure vector).
DEFAULT_WEIGHTS = {"vector": 1.0, "link": 0.25, "tag": 0.15}
HYBRID_POOL  = 30   # vector candidates considered before reranking
SEED_NOTES   = 5    # top vector notes whose neighbours we expand


@dataclass
class Hit:
    score:     float
    note_path: str
    heading:   str
    text:      str
    private:   bool
    source:    str = "vector"   # "vector" | "graph" (M16 — surfaced via the graph)

    def citation(self) -> str:
        return self.note_path + (f"#{self.heading}" if self.heading else "")


class Retriever:
    def __init__(self, embedder, store, weights: dict | None = None, hybrid: bool = True,
                 depth: int = 1):
        self.embedder = embedder
        self.store    = store
        self.hybrid   = hybrid
        self.depth    = max(1, int(depth or 1))   # link-graph expansion hops (M16.5)
        self.weights  = {**DEFAULT_WEIGHTS, **(weights or {})}

    @staticmethod
    def _scope_predicate(scope: dict | None):
        """Filter chunks to a folder prefix and/or a tag (M12 scoped Vault QA)."""
        if not scope:
            return None
        folder = (scope.get("folder") or "").strip()
        tag    = (scope.get("tag") or "").strip().lstrip("#").lower()

        def pred(m: dict) -> bool:
            if folder and not m.get("note_path", "").startswith(folder):
                return False
            if tag and tag not in (m.get("tags") or []):
                return False
            return True
        return pred if (folder or tag) else None

    @staticmethod
    def _hit(score: float, m: dict, source: str = "vector") -> "Hit":
        return Hit(score=score, note_path=m.get("note_path", ""), heading=m.get("heading", ""),
                   text=m.get("text", ""), private=bool(m.get("private", False)), source=source)

    def retrieve(self, query: str, k: int = 6, scope: dict | None = None,
                 hybrid: bool | None = None) -> list[Hit]:
        if not query.strip() or self.store.stats()["chunks"] == 0:
            return []
        qvec = self.embedder.embed_one(query)
        pred = self._scope_predicate(scope)
        use_hybrid = self.hybrid if hybrid is None else hybrid

        graph = LinkGraph(self.store.note_meta, self.store.note_hashes.keys()) if use_hybrid else None
        if not use_hybrid or graph.is_empty:
            return [self._hit(s, m) for s, m in self.store.search(qvec, k=k, predicate=pred)]

        return self._retrieve_hybrid(qvec, k, pred, graph)

    def _retrieve_hybrid(self, qvec, k: int, pred, graph: LinkGraph) -> list[Hit]:
        pool = self.store.search(qvec, k=max(k, HYBRID_POOL), predicate=pred)
        if not pool:
            return []

        # Best chunk per note from the vector pool, and the vector-only top-k notes.
        cand: dict[str, tuple[float, dict]] = {}
        baseline: list[str] = []
        for score, m in pool:
            note = m.get("note_path", "")
            if note not in cand or score > cand[note][0]:
                cand[note] = (score, m)
            if note not in baseline:
                baseline.append(note)
        baseline_top = set(baseline[:k])

        # 1-hop link + shared-tag neighbours of the top vector notes.
        seeds = baseline[:SEED_NOTES]
        link_nb: set[str] = set()
        tag_nb:  set[str] = set()
        for s in seeds:
            link_nb |= graph.neighbors_within(s, self.depth)
            tag_nb  |= graph.tag_neighbors(s)

        # Expand: pull in neighbours that weren't already in the vector pool.
        extra = (link_nb | tag_nb) - set(cand)
        for score, m in self.store.best_chunks_for_notes(qvec, extra, predicate=pred):
            cand[m.get("note_path", "")] = (score, m)

        a, b, c = self.weights["vector"], self.weights["link"], self.weights["tag"]
        ranked = []
        for note, (score, m) in cand.items():
            lp = 1.0 if note in link_nb else 0.0
            tg = 1.0 if note in tag_nb else 0.0
            final  = a * score + b * lp + c * tg
            source = "vector" if note in baseline_top else ("graph" if (lp or tg) else "vector")
            ranked.append((final, score, source, m))

        ranked.sort(key=lambda x: (-x[0], -x[1]))
        return [self._hit(score, m, source) for _, score, source, m in ranked[:k]]

    def build_context(self, hits: list[Hit]) -> str:
        """A cited context block the model is told to answer from."""
        parts = ["[Vault notes — answer ONLY from these and cite the sources you use]"]
        for h in hits:
            parts.append(f"\n[Source: {h.citation()}]\n{h.text}")
        return "\n".join(parts)
