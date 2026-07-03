"""
Tests for Milestone 11 Slice 1 — chunker, vector store, indexer.

Stdlib unittest + a deterministic FAKE embedder (hashing trick), so tests never
download a model or hit the network. Requires numpy (installed with fastembed).

Run with:
    python -m unittest tests.test_rag -v
"""

import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np

from assistant_core.rag.chunker import chunk_markdown
from assistant_core.rag.vector_store import VectorStore
from assistant_core.rag.indexer import VaultIndexer


class FakeEmbedder:
    """Bag-of-hashed-tokens embedding: notes sharing words get similar vectors."""
    name = "fake"
    dim  = 64

    def embed(self, texts):
        texts = list(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in t.lower().split():
                b = int(hashlib.sha1(tok.encode()).hexdigest(), 16) % self.dim
                out[i, b] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (out / norms).astype(np.float32)

    def embed_one(self, text):
        return self.embed([text])[0]


class ChunkerTests(unittest.TestCase):
    def test_heading_aware_chunks(self):
        body = "# Title\n\nintro para\n\n## Alpha\n\naaa one\naaa two\n\n## Beta\n\nbbb\n"
        chunks = chunk_markdown(body)
        headings = {c.heading for c in chunks}
        self.assertIn("Alpha", headings)
        self.assertIn("Beta", headings)
        alpha = next(c for c in chunks if c.heading == "Alpha")
        self.assertIn("aaa one", alpha.text)
        # offsets point into the body
        self.assertEqual(body[alpha.char_start:alpha.char_end].strip().splitlines()[0], "aaa one")

    def test_empty(self):
        self.assertEqual(chunk_markdown("   \n\n"), [])


class VectorStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.emb = FakeEmbedder()
        self.store = VectorStore(Path(self._tmp.name), self.emb.name, self.emb.dim)

    def tearDown(self):
        self._tmp.cleanup()

    def _add(self, path, text, private=False):
        vec = self.emb.embed([text])
        self.store.add_note(path, "h", [{"note_path": path, "heading": "", "text": text,
                                         "char_start": 0, "char_end": len(text), "private": private}], vec)

    def test_search_ranks_by_similarity(self):
        self._add("rocket.md", "rocket stove combustion chamber design")
        self._add("bread.md",  "sourdough bread baking hydration")
        q = self.emb.embed_one("rocket stove design")
        hits = self.store.search(q, k=2)
        self.assertEqual(hits[0][1]["note_path"], "rocket.md")

    def test_remove_and_predicate(self):
        self._add("a.md", "alpha shared word", private=True)
        self._add("b.md", "beta shared word")
        # privacy predicate keeps only non-private
        q = self.emb.embed_one("shared word")
        public = self.store.search(q, k=5, predicate=lambda m: not m["private"])
        self.assertTrue(all(not h[1]["private"] for h in public))
        self.store.remove_note("a.md")
        self.assertNotIn("a.md", self.store.note_hashes)
        self.assertTrue(all(m["note_path"] != "a.md" for m in self.store.meta))

    def test_save_load_roundtrip(self):
        self._add("x.md", "persisted vector content")
        self.store.save()
        reloaded = VectorStore.load_or_new(self.store.index_dir, self.emb.name, self.emb.dim)
        self.assertEqual(reloaded.stats(), {"notes": 1, "chunks": 1})
        q = self.emb.embed_one("persisted content")
        self.assertEqual(reloaded.search(q, k=1)[0][1]["note_path"], "x.md")

    def test_model_change_forces_rebuild(self):
        self._add("x.md", "content"); self.store.save()
        other = VectorStore.load_or_new(self.store.index_dir, "different-model", self.emb.dim)
        self.assertEqual(other.stats(), {"notes": 0, "chunks": 0})


class IndexerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "AI" / "System").mkdir(parents=True)
        self.store = VectorStore(self.vault / ".idx", "fake", 64)
        self.indexer = VaultIndexer(str(self.vault), FakeEmbedder(), self.store)

    def tearDown(self):
        self._tmp.cleanup()

    def _note(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_incremental_add_skip_update_remove(self):
        self._note("a.md", "alpha content one")
        self._note("b.md", "beta content two")
        self._note("AI/System/secret.md", "should be excluded")
        r1 = self.indexer.reindex()
        self.assertEqual((r1["added"], r1["removed"]), (2, 0))   # AI/System excluded
        self.assertEqual(self.store.stats()["notes"], 2)

        r2 = self.indexer.reindex()                              # nothing changed
        self.assertEqual((r2["added"], r2["updated"], r2["skipped"]), (0, 0, 2))

        self._note("a.md", "alpha content one CHANGED")          # modify one
        r3 = self.indexer.reindex()
        self.assertEqual((r3["updated"], r3["skipped"]), (1, 1))

        (self.vault / "b.md").unlink()                           # delete one
        r4 = self.indexer.reindex()
        self.assertEqual(r4["removed"], 1)
        self.assertEqual(self.store.stats()["notes"], 1)

    def test_retrieval_after_index(self):
        self._note("rocket.md", "## Build\n\nrocket stove combustion chamber")
        self._note("bread.md",  "## Bake\n\nsourdough hydration schedule")
        self.indexer.reindex()
        q = FakeEmbedder().embed_one("rocket stove")
        self.assertEqual(self.store.search(q, k=1)[0][1]["note_path"], "rocket.md")


class _FakeRouter:
    def __init__(self):
        self.captured_private = None

    def generate(self, messages, system_prompt="", max_tokens=2048, temperature=0.3,
                 private=False, allow_webui=True, **kw):
        self.captured_private = private
        return "ANSWER", "groq"


class RetrieverQATests(unittest.TestCase):
    def setUp(self):
        from assistant_core.rag.retriever import Retriever
        self._tmp = tempfile.TemporaryDirectory()
        self.emb = FakeEmbedder()
        self.store = VectorStore(Path(self._tmp.name), self.emb.name, self.emb.dim)
        self._add("rocket.md", "Build", "rocket stove combustion chamber design", private=False)
        self._add("secret.md", "",      "private rocket fuel formula",            private=True)
        self.retr = Retriever(self.emb, self.store)

    def tearDown(self):
        self._tmp.cleanup()

    def _add(self, path, heading, text, private):
        vec = self.emb.embed([(heading + "\n" + text) if heading else text])
        self.store.add_note(path, "h", [{"note_path": path, "heading": heading, "text": text,
                                         "char_start": 0, "char_end": len(text), "private": private}], vec)

    def test_retrieve_and_context(self):
        hits = self.retr.retrieve("rocket stove combustion", k=2)
        self.assertEqual(hits[0].note_path, "rocket.md")
        ctx = self.retr.build_context(hits)
        self.assertIn("[Source: rocket.md#Build]", ctx)

    def test_qa_public_source_not_private(self):
        from assistant_core.rag.qa import run_vault_qa
        router = _FakeRouter()
        res = run_vault_qa(router, self.retr, "rocket stove combustion chamber", k=1)
        self.assertEqual(res["answer"], "ANSWER")
        self.assertEqual(res["sources"], ["rocket.md#Build"])
        self.assertFalse(res["private"])           # top hit is the public note
        self.assertFalse(router.captured_private)

    def test_qa_forces_private_when_any_source_private(self):
        from assistant_core.rag.qa import run_vault_qa
        router = _FakeRouter()
        res = run_vault_qa(router, self.retr, "rocket fuel formula", k=2)  # pulls in the private note
        self.assertTrue(res["private"])
        self.assertTrue(router.captured_private)   # privacy forced → no-train routing

    def test_empty_index_no_answer(self):
        from assistant_core.rag.retriever import Retriever
        from assistant_core.rag.qa import run_vault_qa
        empty = Retriever(self.emb, VectorStore(Path(self._tmp.name) / "empty", "fake", 64))
        res = run_vault_qa(_FakeRouter(), empty, "anything")
        self.assertIsNone(res["answer"])
        self.assertEqual(res["sources"], [])


class RagServiceTests(unittest.TestCase):
    def setUp(self):
        from assistant_core.rag.service import RagService
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "AI" / "System").mkdir(parents=True)
        self.svc = RagService(
            {"vault_path": str(self.vault), "index_on_startup": True},
            index_dir=self.vault / ".idx", embedder=FakeEmbedder(),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _note(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_enabled_flag(self):
        self.assertTrue(self.svc.enabled)

    def test_reindex_and_excludes(self):
        self._note("a.md", "alpha note")
        self._note("AI/System/x.md", "excluded")
        rep = self.svc.reindex()
        self.assertEqual(rep["added"], 1)            # AI/System excluded
        self.assertFalse(self.svc.should_index("AI/System/x.md"))
        self.assertTrue(self.svc.has_index())

    def test_maybe_index_note_only_on_change(self):
        p = self._note("a.md", "first version")
        self.svc.reindex()
        # unchanged content → no re-index
        self.assertFalse(self.svc.maybe_index_note("a.md", "first version"))
        # changed content → re-index
        self.assertTrue(self.svc.maybe_index_note("a.md", "second version entirely"))
        # excluded path → never
        self.assertFalse(self.svc.maybe_index_note("AI/System/x.md", "whatever"))

    def test_scoped_retrieval_by_folder_and_tag(self):
        from assistant_core.rag.retriever import Retriever
        self._note("proj/a.md", "---\ntags: alpha\n---\n\nshared keyword content here")
        self._note("other/b.md", "shared keyword content here too #beta")
        self.svc.reindex()
        retr = Retriever(self.svc.embedder, self.svc.store)
        # folder scope → only proj/
        folder_hits = retr.retrieve("shared keyword", k=5, scope={"folder": "proj/"})
        self.assertTrue(folder_hits and all(h.note_path.startswith("proj/") for h in folder_hits))
        # tag scope (#beta lives only in other/b.md)
        tag_hits = retr.retrieve("shared keyword", k=5, scope={"tag": "beta"})
        self.assertTrue(tag_hits and all(h.note_path == "other/b.md" for h in tag_hits))
        # frontmatter tag "alpha" → only proj/a.md
        alpha_hits = retr.retrieve("shared keyword", k=5, scope={"tag": "alpha"})
        self.assertTrue(alpha_hits and all(h.note_path == "proj/a.md" for h in alpha_hits))

    def test_relevant_notes_ranks_and_excludes_self(self):
        self._note("rocket.md", "rocket stove combustion chamber design")
        self._note("stove.md",  "wood stove combustion and heat")        # shares words → related
        self._note("bread.md",  "sourdough hydration schedule")          # unrelated
        self.svc.reindex()
        rel = self.svc.relevant_notes("rocket.md", k=5)
        paths = [r["path"] for r in rel]
        self.assertNotIn("rocket.md", paths)         # never itself
        self.assertEqual(paths[0], "stove.md")        # closest neighbour first


class _VocabEmbedder:
    """Collision-free bag-of-words: each distinct token gets its own dimension, so
    cosine == shared-word count / (||a|| ||b||) exactly — deterministic for the
    hybrid reranking asserts (no hash collisions)."""
    name = "vocab"
    dim  = 256

    def __init__(self):
        self._ix: dict[str, int] = {}

    def embed(self, texts):
        texts = list(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in t.lower().split():
                if tok not in self._ix:
                    self._ix[tok] = len(self._ix)
                out[i, self._ix[tok] % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (out / norms).astype(np.float32)

    def embed_one(self, text):
        return self.embed([text])[0]


class HybridRetrievalTests(unittest.TestCase):
    """M16 — link/tag graph capture + graph-aware reranking."""

    def setUp(self):
        from assistant_core.rag.retriever import Retriever
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        self.emb = _VocabEmbedder()
        self.store = VectorStore(self.vault / ".idx", self.emb.name, self.emb.dim)
        self.indexer = VaultIndexer(str(self.vault), self.emb, self.store)
        self.Retriever = Retriever

    def tearDown(self):
        self._tmp.cleanup()

    def _note(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_extract_links_and_tags_recorded(self):
        from assistant_core.rag.indexer import _extract_links
        self.assertEqual(
            _extract_links("see [[Insulation]], [[notes/Stove|the stove]] and [[Combustion#Air]]"),
            ["combustion", "insulation", "notes/stove"],
        )
        self._note("rocket.md", "rocket stove combustion\n#engine\nlinks [[insulation]]")
        self.indexer.reindex()
        info = self.store.note_meta["rocket.md"]
        self.assertIn("insulation", info["links"])
        self.assertIn("engine", info["tags"])

    def test_link_neighbour_promoted_into_results(self):
        # rocket is the top vector hit and links to insulation (which shares no query words).
        self._note("rocket.md", "rocket stove combustion chamber\nlinks [[insulation]]")
        self._note("insulation.md", "ceramic fiber blanket lining")          # 0 query words
        self._note("d1.md", "stove lamp post bench")                          # shares 'stove'
        self._note("d2.md", "combustion lamp post bench")                     # shares 'combustion'
        self.indexer.reindex()
        retr = self.Retriever(self.emb, self.store, weights={"link": 0.5})

        vec = {h.note_path for h in retr.retrieve("rocket stove combustion", k=2, hybrid=False)}
        hyb = retr.retrieve("rocket stove combustion", k=2, hybrid=True)
        hyb_paths = {h.note_path for h in hyb}

        self.assertNotIn("insulation.md", vec)        # vector alone misses it
        self.assertIn("insulation.md", hyb_paths)     # the link pulls it in
        ins = next(h for h in hyb if h.note_path == "insulation.md")
        self.assertEqual(ins.source, "graph")         # labelled for the UI

    def test_shared_tag_neighbour_promoted(self):
        self._note("rocket.md", "rocket stove combustion chamber\n#engine")
        self._note("manual.md", "user guide instructions\n#engine")          # shares tag, 0 query words
        self._note("d1.md", "stove lamp post bench")
        self._note("d2.md", "combustion lamp post bench")
        self.indexer.reindex()
        retr = self.Retriever(self.emb, self.store, weights={"tag": 0.5})

        vec = {h.note_path for h in retr.retrieve("rocket stove combustion", k=2, hybrid=False)}
        hyb = {h.note_path for h in retr.retrieve("rocket stove combustion", k=2, hybrid=True)}
        self.assertNotIn("manual.md", vec)
        self.assertIn("manual.md", hyb)

    def test_private_note_excluded_from_graph(self):
        self._note("rocket.md", "rocket stove combustion\nlinks [[secret]]")
        self._note("secret.md", "---\nprivate: true\n---\n\nrocket fuel formula\n#engine [[rocket]]")
        self.indexer.reindex()
        # the private note contributes no links/tags to the graph
        self.assertEqual(self.store.note_meta["secret.md"], {"links": [], "tags": []})

    def test_depth_two_reaches_second_hop(self):
        # rocket -> middle -> faraway. faraway is 2 hops from the only seed (rocket).
        self._note("rocket.md", "rocket stove combustion chamber\nlinks [[middle]]")
        self._note("middle.md", "alpha bravo charlie\nlinks [[faraway]]")   # 0 query words
        self._note("faraway.md", "delta echo foxtrot")                      # 0 query words
        for d in ("rocket", "stove", "combustion", "chamber"):              # 4 distractors → seeds = rocket only
            self._note(f"d_{d}.md", f"{d} lamp post bench")
        self.indexer.reindex()
        q = "rocket stove combustion chamber"

        d1 = {h.note_path for h in
              self.Retriever(self.emb, self.store, weights={"link": 0.5}, depth=1).retrieve(q, k=3)}
        d2 = {h.note_path for h in
              self.Retriever(self.emb, self.store, weights={"link": 0.5}, depth=2).retrieve(q, k=3)}
        self.assertNotIn("faraway.md", d1)     # 2nd hop unreachable at depth 1
        self.assertIn("faraway.md", d2)        # reached at depth 2

    def test_degrades_to_vector_without_graph(self):
        # A store with no note_meta graph (links/tags) → hybrid == pure vector order.
        store = VectorStore(self.vault / ".idx2", self.emb.name, self.emb.dim)
        for path, text in [("a.md", "rocket stove combustion"), ("b.md", "bread sourdough"),
                           ("c.md", "stove heat output")]:
            store.add_note(path, "h", [{"note_path": path, "heading": "", "text": text,
                                        "char_start": 0, "char_end": len(text), "private": False}],
                           self.emb.embed([text]))      # no note_info → empty graph
        retr = self.Retriever(self.emb, store)
        a = [h.note_path for h in retr.retrieve("rocket stove", k=3, hybrid=True)]
        b = [h.note_path for h in retr.retrieve("rocket stove", k=3, hybrid=False)]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
