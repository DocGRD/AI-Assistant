"""
Vector store — Milestone 11.

A tiny local index: an (N, dim) float32 matrix of L2-normalised embeddings plus a
parallel metadata list, persisted to `data/vault_index/` (service-local, outside
the vault, git-ignored, fully rebuildable from the markdown). For a 435-note vault
(~2–4k chunks) a brute-force cosine (a single matmul) is sub-10 ms — no FAISS/Chroma.
"""

import json
import logging
import numpy as np
from pathlib import Path

logger = logging.getLogger("assistant")


class VectorStore:
    # Bump when the per-chunk metadata schema changes (forces a clean rebuild).
    SCHEMA = 3   # 2: adds `tags` per chunk (M12). 3: adds per-note graph meta — links/tags (M16)

    def __init__(self, index_dir, model_name: str, dim: int):
        self.index_dir   = Path(index_dir)
        self.model_name  = model_name
        self.dim         = dim
        self.vectors     = np.zeros((0, dim), dtype=np.float32)
        self.meta: list[dict]        = []
        self.note_hashes: dict[str, str] = {}   # rel_path -> content hash (incremental)
        # M16 — per-note structural graph: rel_path -> {"links": [...], "tags": [...]}.
        self.note_meta: dict[str, dict]  = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def load_or_new(cls, index_dir, model_name: str, dim: int) -> "VectorStore":
        store = cls(index_dir, model_name, dim)
        try:
            store._load()
        except Exception as exc:                       # corrupt/old index → safe rebuild
            logger.warning(f"[RAG] Index load failed ({exc}) — starting fresh")
            store._reset()
        return store

    def _load(self) -> None:
        manifest_path = self.index_dir / "manifest.json"
        if not manifest_path.exists():
            return
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("model") != self.model_name or manifest.get("dim") != self.dim
                or manifest.get("schema") != self.SCHEMA):
            logger.info("[RAG] Index model/dim/schema changed — rebuild needed")
            self._reset()
            return
        self.vectors     = np.load(self.index_dir / "vectors.npy")
        self.meta        = json.loads((self.index_dir / "meta.json").read_text(encoding="utf-8"))
        self.note_hashes = manifest.get("note_hashes", {})
        self.note_meta   = manifest.get("note_meta", {})
        logger.info(f"[RAG] Loaded index: {len(self.note_hashes)} notes, {len(self.meta)} chunks")

    def _reset(self) -> None:
        self.vectors     = np.zeros((0, self.dim), dtype=np.float32)
        self.meta        = []
        self.note_hashes = {}
        self.note_meta   = {}

    def save(self) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        np.save(self.index_dir / "vectors.npy", self.vectors)
        (self.index_dir / "meta.json").write_text(
            json.dumps(self.meta, ensure_ascii=False), encoding="utf-8")
        (self.index_dir / "manifest.json").write_text(json.dumps({
            "model": self.model_name, "dim": self.dim, "schema": self.SCHEMA,
            "note_hashes": self.note_hashes, "note_meta": self.note_meta,
            "chunks": len(self.meta),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def remove_note(self, rel_path: str) -> None:
        keep = [i for i, m in enumerate(self.meta) if m.get("note_path") != rel_path]
        if len(keep) != len(self.meta):
            self.vectors = self.vectors[keep] if keep else np.zeros((0, self.dim), dtype=np.float32)
            self.meta    = [self.meta[i] for i in keep]
        self.note_hashes.pop(rel_path, None)
        self.note_meta.pop(rel_path, None)

    def add_note(self, rel_path: str, note_hash: str, metas: list[dict], vecs: np.ndarray,
                 note_info: dict | None = None) -> None:
        self.remove_note(rel_path)
        if len(vecs):
            vecs = vecs.astype(np.float32)
            self.vectors = np.vstack([self.vectors, vecs]) if len(self.vectors) else vecs
            self.meta.extend(metas)
        self.note_hashes[rel_path] = note_hash
        self.note_meta[rel_path]   = note_info or {}

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def search(self, qvec: np.ndarray, k: int = 6, predicate=None) -> list[tuple[float, dict]]:
        """Top-k by cosine (vectors are normalised). `predicate(meta)` filters candidates."""
        if len(self.vectors) == 0:
            return []
        scores = self.vectors @ np.asarray(qvec, dtype=np.float32)
        order  = np.argsort(-scores)
        out: list[tuple[float, dict]] = []
        for i in order:
            m = self.meta[i]
            if predicate is not None and not predicate(m):
                continue
            out.append((float(scores[i]), m))
            if len(out) >= k:
                break
        return out

    def best_chunks_for_notes(self, qvec: np.ndarray, note_paths, predicate=None
                              ) -> list[tuple[float, dict]]:
        """Best-scoring chunk (passing `predicate`) for each requested note (M16 graph
        expansion — surfaces a linked/tagged neighbour even if it sits outside top-k)."""
        want = set(note_paths)
        if len(self.vectors) == 0 or not want:
            return []
        scores = self.vectors @ np.asarray(qvec, dtype=np.float32)
        best: dict[str, tuple[float, dict]] = {}
        for i, m in enumerate(self.meta):
            p = m.get("note_path")
            if p not in want:
                continue
            if predicate is not None and not predicate(m):
                continue
            s = float(scores[i])
            if p not in best or s > best[p][0]:
                best[p] = (s, m)
        return list(best.values())

    def stats(self) -> dict:
        return {"notes": len(self.note_hashes), "chunks": len(self.meta)}
