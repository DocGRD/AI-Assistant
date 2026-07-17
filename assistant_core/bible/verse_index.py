"""Verse-level embedding index for the Bible reader.

The personal RAG index chunks notes by size (chapter-level), which is too coarse for "which OTHER
verses mean something like THIS verse?". This builds a dedicated, lean index with ONE embedding per
verse, so the reader can show per-verse "Related by meaning" links (deduplicated against the
public-domain cross-references). Kept separate from the personal RAG so it never floods Vault QA.

Only the offline, public-domain base version (WEB) is indexed. Storage: a float32 matrix of L2-
normalised vectors + a parallel list of canonical refs — cosine similarity is then a matrix-vector dot.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import numpy as np

logger = logging.getLogger("assistant")

# book-slug -> display name, for labels (matches the note folder slugs)
_BOOKS = {
    "genesis": "Genesis", "exodus": "Exodus", "leviticus": "Leviticus", "numbers": "Numbers",
    "deuteronomy": "Deuteronomy", "joshua": "Joshua", "judges": "Judges", "ruth": "Ruth",
    "1-samuel": "1 Samuel", "2-samuel": "2 Samuel", "1-kings": "1 Kings", "2-kings": "2 Kings",
    "1-chronicles": "1 Chronicles", "2-chronicles": "2 Chronicles", "ezra": "Ezra",
    "nehemiah": "Nehemiah", "esther": "Esther", "job": "Job", "psalms": "Psalms",
    "proverbs": "Proverbs", "ecclesiastes": "Ecclesiastes", "song-of-solomon": "Song of Solomon",
    "isaiah": "Isaiah", "jeremiah": "Jeremiah", "lamentations": "Lamentations", "ezekiel": "Ezekiel",
    "daniel": "Daniel", "hosea": "Hosea", "joel": "Joel", "amos": "Amos", "obadiah": "Obadiah",
    "jonah": "Jonah", "micah": "Micah", "nahum": "Nahum", "habakkuk": "Habakkuk",
    "zephaniah": "Zephaniah", "haggai": "Haggai", "zechariah": "Zechariah", "malachi": "Malachi",
    "matthew": "Matthew", "mark": "Mark", "luke": "Luke", "john": "John", "acts": "Acts",
    "romans": "Romans", "1-corinthians": "1 Corinthians", "2-corinthians": "2 Corinthians",
    "galatians": "Galatians", "ephesians": "Ephesians", "philippians": "Philippians",
    "colossians": "Colossians", "1-thessalonians": "1 Thessalonians",
    "2-thessalonians": "2 Thessalonians", "1-timothy": "1 Timothy", "2-timothy": "2 Timothy",
    "titus": "Titus", "philemon": "Philemon", "hebrews": "Hebrews", "james": "James",
    "1-peter": "1 Peter", "2-peter": "2 Peter", "1-john": "1 John", "2-john": "2 John",
    "3-john": "3 John", "jude": "Jude", "revelation": "Revelation",
}
_EMSPACE = " "


def _clean_verse(raw: str) -> str:
    """Text of a verse line `**N** words  \\n words ^vN` → plain words (drop number, anchor, markup)."""
    t = raw.replace(_EMSPACE, " ")
    t = re.sub(r"\^v\d+", "", t)                  # block anchor
    t = re.sub(r"^\*\*\d+\*\*\s*", "", t)         # leading **verse-number**
    t = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", t)   # any wikilinks -> alias
    t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\*\*([^*]*)\*\*", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _iter_verses(vault: Path, version: str = "web"):
    """Yield (book_slug, chapter, verse_num, text) for every verse note of `version`."""
    root = vault / "bible"
    for note in sorted(root.glob(f"*/{version}/*.md")):
        m = re.match(r"(.+)-(\d+)$", note.stem)
        if not m or m.group(1) not in _BOOKS:
            continue                              # skip book MOCs / odd names
        book, chapter = m.group(1), int(m.group(2))
        cur_num, cur_parts = None, []
        for raw in note.read_text(encoding="utf-8", errors="replace").splitlines():
            vm = re.match(r"^\*\*(\d+)\*\*", raw)
            if vm:
                if cur_num is not None:
                    yield book, chapter, cur_num, _clean_verse(" ".join(cur_parts))
                cur_num, cur_parts = int(vm.group(1)), [raw]
            elif cur_num is not None and raw.strip() and not raw.startswith(("#", ">", "[[", "---")):
                cur_parts.append(raw)             # continuation (poetry stich) of the current verse
        if cur_num is not None:
            yield book, chapter, cur_num, _clean_verse(" ".join(cur_parts))


class VerseIndex:
    """One L2-normalised embedding per Bible verse; cosine top-K over the matrix."""

    def __init__(self, data_dir, embedder):
        self.dir = Path(data_dir)
        self.embedder = embedder
        self.refs: list[str] = []      # "matthew.1.23"
        self.vecs: np.ndarray | None = None
        self._pos: dict[str, int] = {}
        self._by_chapter: dict[str, list[str]] = {}

    # --- persistence -------------------------------------------------------
    def load(self) -> bool:
        vp, mp = self.dir / "verse_vectors.npy", self.dir / "verse_meta.json"
        if not (vp.exists() and mp.exists()):
            return False
        try:
            self.vecs = np.load(vp)
            self.refs = json.loads(mp.read_text(encoding="utf-8"))["refs"]
            self._reindex()
            logger.info(f"[VerseIndex] loaded {len(self.refs)} verses")
            return True
        except Exception as exc:
            logger.warning(f"[VerseIndex] load failed: {exc}")
            return False

    def _reindex(self) -> None:
        self._pos = {r: i for i, r in enumerate(self.refs)}
        self._by_chapter = {}
        for r in self.refs:
            b, c, _ = r.rsplit(".", 2)
            self._by_chapter.setdefault(f"{b}.{c}", []).append(r)

    # --- build -------------------------------------------------------------
    def build(self, vault, batch: int = 256) -> dict:
        vault = Path(vault)
        refs, texts = [], []
        for book, chapter, vnum, text in _iter_verses(vault):
            if not text:
                continue
            refs.append(f"{book}.{chapter}.{vnum}")
            texts.append(text)
        if not texts:
            return {"verses": 0, "error": "no WEB verses found under bible/"}
        vecs = np.zeros((len(texts), self.embedder.dim), dtype=np.float32)
        for i in range(0, len(texts), batch):
            vecs[i:i + batch] = np.asarray(self.embedder.embed(texts[i:i + batch]), dtype=np.float32)
        # L2-normalise so cosine == dot
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs /= norms
        self.dir.mkdir(parents=True, exist_ok=True)
        np.save(self.dir / "verse_vectors.npy", vecs)
        (self.dir / "verse_meta.json").write_text(json.dumps({"refs": refs, "dim": self.embedder.dim}),
                                                   encoding="utf-8")
        self.refs, self.vecs = refs, vecs
        self._reindex()
        logger.info(f"[VerseIndex] built {len(refs)} verse embeddings")
        return {"verses": len(refs)}

    # --- query -------------------------------------------------------------
    def ready(self) -> bool:
        return self.vecs is not None and len(self.refs) > 0

    def _label(self, ref: str) -> dict:
        b, c, v = ref.rsplit(".", 2)
        return {"b": b, "c": int(c), "v": int(v), "n": f"{_BOOKS.get(b, b)} {c}:{v}"}

    def similar(self, ref: str, k: int = 6) -> list[dict]:
        i = self._pos.get(ref)
        if i is None or self.vecs is None:
            return []
        scores = self.vecs @ self.vecs[i]
        base = ref.rsplit(".", 1)[0]                # "book.chapter" — exclude same chapter
        order = np.argsort(-scores)
        out = []
        for j in order:
            r = self.refs[j]
            if r == ref or r.rsplit(".", 1)[0] == base:
                continue
            out.append({**self._label(r), "score": float(scores[j])})
            if len(out) >= k:
                break
        return out

    def chapter_similar(self, book: str, chapter: int, k: int = 4) -> dict:
        """{verse_num: [similar refs]} for every verse of a chapter — one request per chapter."""
        res = {}
        for ref in self._by_chapter.get(f"{book}.{chapter}", []):
            v = ref.rsplit(".", 1)[1]
            res[v] = self.similar(ref, k=k)
        return res
