"""
Vault indexer — Milestone 11.

Walks the vault, chunks each note, embeds the chunks locally, and stores them.
Incremental: a note is re-embedded only when its content hash changed; deleted
notes are dropped. Embeddings are local, so private notes are safe to index — the
`private` flag is recorded per chunk so retrieval can route privately when needed.
"""

import hashlib
import logging
import re
import numpy as np
from pathlib import Path

from assistant_core.watcher.frontmatter_parser import FrontmatterParser
from assistant_core.rag.chunker import chunk_markdown
from assistant_core.media.excalidraw import is_excalidraw, extract_excalidraw_text

logger = logging.getLogger("assistant")

# Folders not worth indexing: system files, episode logs, transient consolidation
# proposals, the derived entity graph, and the plugin handshake notes.
DEFAULT_EXCLUDES = ("AI/System", "AI/Memory/Episodes", "AI/Memory/proposed",
                    "AI/Graph", "AI/Chat")


def _truthy(v) -> bool:
    return str(v).strip().strip('"\'').lower() in ("true", "yes", "1", "on")


def _extract_tags(fm: dict, body: str) -> list[str]:
    """Tags from frontmatter `tags:` (comma/space/list) + inline `#tags` in the body."""
    tags: set[str] = set()
    raw = fm.get("tags") or fm.get("tag") or ""
    if raw:
        for t in re.split(r"[,\s]+", str(raw).strip().strip("[]")):
            t = t.strip().strip("\"'").lstrip("#")
            if t:
                tags.add(t.lower())
    for m in re.finditer(r"(?:^|\s)#([A-Za-z0-9_][\w/-]*)", body):
        tags.add(m.group(1).lower())
    return sorted(tags)


def _extract_links(body: str) -> list[str]:
    """Normalised `[[wikilink]]` targets (M16 graph). Strips `|alias`, `#heading`,
    and the `.md` extension; lower-cased for resolution. The link graph resolves
    these to actual note paths at query time."""
    links: set[str] = set()
    for m in re.finditer(r"\[\[([^\]]+)\]\]", body):
        target = m.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        target = target.replace("\\", "/").removesuffix(".md").strip().lower()
        if target:
            links.add(target)
    return sorted(links)


class VaultIndexer:
    def __init__(self, vault_path, embedder, store, excludes=DEFAULT_EXCLUDES):
        self.vault    = Path(vault_path)
        self.embedder = embedder
        self.store    = store
        self.excludes = tuple(excludes)

    def _excluded(self, rel: str) -> bool:
        rel = rel.replace("\\", "/")
        return any(rel == e or rel.startswith(e + "/") for e in self.excludes)

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha1(content.encode("utf-8")).hexdigest()

    def index_note(self, rel_path: str, content: str | None = None) -> int:
        """(Re)index a single note. Returns the chunk count. Used by reindex + the watcher."""
        rel_path = rel_path.replace("\\", "/")    # forward slashes everywhere (match Obsidian)
        full = self.vault / rel_path
        if content is None:
            if not full.exists():
                self.store.remove_note(rel_path)
                return 0
            content = full.read_text(encoding="utf-8")

        fm, body = FrontmatterParser.extract(content)
        private  = _truthy(fm.get("private", ""))
        tags     = _extract_tags(fm, body)
        # M19 — for an Excalidraw drawing, index just its typed text (the Text Elements),
        # not the scene JSON. Keeps drawings searchable without embedding noise.
        if is_excalidraw(rel_path, fm):
            drawing_text = extract_excalidraw_text(content)
            if drawing_text:
                body = drawing_text
        # M16 — per-note structural graph info (links + tags), private notes excluded
        # from the graph so a public note can't reach private content via a link.
        note_info = {"links": [] if private else _extract_links(body),
                     "tags":  [] if private else tags}
        chunks   = chunk_markdown(body)
        if not chunks:
            self.store.add_note(rel_path, self._hash(content), [],
                                np.zeros((0, self.embedder.dim), dtype=np.float32),
                                note_info=note_info)
            return 0

        # Embed heading + text so the heading gives the chunk context.
        embed_texts = [(c.heading + "\n" + c.text) if c.heading else c.text for c in chunks]
        vecs  = self.embedder.embed(embed_texts)
        metas = [{
            "note_path": rel_path, "heading": c.heading, "text": c.text[:1000],
            "char_start": c.char_start, "char_end": c.char_end,
            "private": private, "tags": tags,
        } for c in chunks]
        self.store.add_note(rel_path, self._hash(content), metas, vecs, note_info=note_info)
        return len(chunks)

    def reindex(self, full: bool = False, save: bool = True) -> dict:
        """Incrementally bring the index in sync with the vault. Returns a small report."""
        report = {"added": 0, "updated": 0, "removed": 0, "skipped": 0, "chunks": 0}
        on_disk: set[str] = set()

        for f in self.vault.rglob("*.md"):
            rel = str(f.relative_to(self.vault)).replace("\\", "/")
            if self._excluded(rel):
                continue
            on_disk.add(rel)
            try:
                content = f.read_text(encoding="utf-8")
            except Exception as exc:
                logger.debug(f"[RAG] Skip unreadable {rel}: {exc}")
                continue

            existing = self.store.note_hashes.get(rel)
            if not full and existing == self._hash(content):
                report["skipped"] += 1
                continue

            report["chunks"] += self.index_note(rel, content=content)
            report["added" if existing is None else "updated"] += 1

        for rel in list(self.store.note_hashes.keys()):
            if rel not in on_disk:
                self.store.remove_note(rel)
                report["removed"] += 1

        if save:
            self.store.save()
        return report
