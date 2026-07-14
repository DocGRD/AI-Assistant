"""
RagService — Milestone 11.

One shared holder for the index so startup, the watcher, and the terminal/HTTP
commands use a single loaded store + embedder (the model loads lazily on first
embed). `enabled` (settings `index_on_startup`) gates *writing* the index, so only
the always-on GPU box indexes — the laptop never does.

Thread-safe: a lock guards index mutations (startup bulk reindex, watcher updates)
and is reused by retrieval reads in the HTTP path (Slice 4).
"""

import logging
import threading
from pathlib import Path

from assistant_core.rag.vector_store import VectorStore
from assistant_core.rag.indexer import VaultIndexer
from assistant_core.rag.retriever import Retriever

logger = logging.getLogger("assistant")


class RagService:
    def __init__(self, config: dict | None = None, index_dir=None, embedder=None):
        self.config     = config or {}
        self.vault_path = self.config.get("vault_path", "")
        # Only the indexing machine (the box) writes the index.
        self.enabled    = bool(self.config.get("index_on_startup", False))
        from assistant_core.paths import DATA_DIR
        self.index_dir  = Path(index_dir) if index_dir else DATA_DIR / "vault_index"
        self._lock      = threading.Lock()
        self._embedder  = embedder    # injectable for tests
        self._store     = None
        self._indexer   = None

    # ------------------------------------------------------------------
    # Lazy components
    # ------------------------------------------------------------------

    @property
    def embedder(self):
        if self._embedder is None:
            backend = str((self.config or {}).get("embedding_backend", "fastembed")).lower()
            if backend == "ollama":
                # Ollama embedding model — shares its lightweight GGML GPU runtime with the local
                # LLM, so both fit on a small GPU (unlike onnxruntime-gpu's ~2 GB cuDNN context).
                from assistant_core.rag.embedder import OllamaEmbedder
                self._embedder = OllamaEmbedder(self.config)
            else:
                from assistant_core.rag.embedder import LocalEmbedder
                self._embedder = LocalEmbedder(self.config)
        return self._embedder

    def close(self) -> None:
        """Release the embedding model + its GPU memory (called before a restart so the CUDA
        arena is freed cleanly instead of leaking across the in-place os.execv restart)."""
        if self._embedder is not None:
            try:
                self._embedder.close()
            except Exception:
                pass

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            self._store = VectorStore.load_or_new(self.index_dir, self.embedder.name, self.embedder.dim)
        return self._store

    @property
    def indexer(self) -> VaultIndexer:
        if self._indexer is None:
            self._indexer = VaultIndexer(self.vault_path, self.embedder, self.store)
        return self._indexer

    # ------------------------------------------------------------------
    # Indexing (write — only on the enabled machine)
    # ------------------------------------------------------------------

    def should_index(self, rel_path: str) -> bool:
        return not self.indexer._excluded(rel_path)

    def reindex(self, full: bool = False) -> dict:
        with self._lock:
            return self.indexer.reindex(full=full)

    def maybe_index_note(self, rel_path: str, content: str) -> bool:
        """Re-embed a single note only if its content actually changed. Returns True if re-indexed."""
        rel_path = rel_path.replace("\\", "/")
        if not self.should_index(rel_path):
            return False
        with self._lock:
            if self.store.note_hashes.get(rel_path) == VaultIndexer._hash(content):
                return False
            self.indexer.index_note(rel_path, content=content)
            self.store.save()
        logger.info(f"[RAG] Re-indexed changed note: {rel_path}")
        return True

    # ------------------------------------------------------------------
    # Query (read)
    # ------------------------------------------------------------------

    def retriever(self) -> Retriever:
        # M16 — hybrid (graph-aware) retrieval is on by default; tune via settings.json
        # `hybrid_weights` ({vector,link,tag}) or disable with `hybrid_retrieval: false`.
        return Retriever(
            self.embedder, self.store,
            weights=self.config.get("hybrid_weights"),
            hybrid=bool(self.config.get("hybrid_retrieval", True)),
            depth=int(self.config.get("hybrid_depth", 1)),
        )

    def relevant_notes(self, note_path: str, k: int = 5) -> list[dict]:
        """
        Notes semantically related to `note_path`, using its stored chunk vectors
        (free — no re-embed). If the note isn't indexed, embed its text once.
        Returns [{path, score}] excluding the note itself, deduped by note_path.
        """
        import numpy as np
        from assistant_core.rag.embedder import normalize
        note_path = note_path.replace("\\", "/")
        with self._lock:
            store = self.store
            if store.stats()["chunks"] == 0:
                return []
            own = [i for i, m in enumerate(store.meta) if m.get("note_path") == note_path]
            if own:
                qvec = normalize(store.vectors[own].mean(axis=0))
            else:
                from pathlib import Path as _P
                from assistant_core.watcher.frontmatter_parser import FrontmatterParser
                full = _P(self.vault_path) / note_path
                if not full.exists():
                    return []
                _, body = FrontmatterParser.extract(full.read_text(encoding="utf-8"))
                if not body.strip():
                    return []
                qvec = self.embedder.embed_one(body[:2000])

            best: dict[str, float] = {}
            for score, m in store.search(qvec, k=50, predicate=lambda mm: mm.get("note_path") != note_path):
                p = m.get("note_path")
                if p and (p not in best or score > best[p]):
                    best[p] = score
        ranked = sorted(best.items(), key=lambda kv: -kv[1])[:k]
        return [{"path": p, "score": round(float(s), 3)} for p, s in ranked]

    def stats(self) -> dict:
        return self.store.stats()

    def has_index(self) -> bool:
        return self.store.stats()["chunks"] > 0
