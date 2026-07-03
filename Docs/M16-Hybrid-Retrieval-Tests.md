# M16 — Hybrid (Graph-Aware) Retrieval Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

Vault QA now blends vector similarity with the vault's `[[links]]` + `#tags`. See [[Project-State]]
M16 and [[Deployment-Guide]] §M16. Zero new cost (no LLM).

---

## Section 1 — Automated (deterministic)

### T16.01 — Hybrid retrieval unit tests
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_rag -v`

**Expected:** Pass, including the M16 `HybridRetrievalTests`:
- `test_extract_links_and_tags_recorded` — `[[wikilinks]]` + tags land in `store.note_meta`.
- `test_link_neighbour_promoted_into_results` — a note linked from the top hit (sharing no query
  words) is pulled into results by the link boost and is **absent** from vector-only results; its
  hit is labelled `source="graph"`.
- `test_shared_tag_neighbour_promoted` — a note sharing a `#tag` with the top hit is promoted.
- `test_private_note_excluded_from_graph` — a `private: true` note contributes no links/tags.
- `test_degrades_to_vector_without_graph` — with no graph in the index, hybrid order == vector order.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

## Section 2 — Live (box with an index)

### T16.02 — One-time reindex (SCHEMA 3)
**Steps:** On the indexing host: `python -m assistant_core --terminal` → `vault:reindex`.

**Expected:** The index rebuilds once (manifest SCHEMA bumped 2→3); `vault:reindex` reports notes/chunks.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

### T16.03 — A linked note surfaces as a graph source
**Steps:** Pick note **A** that `[[links]]` to note **B**, where B is topically related but uses
different words. Ask a question answered mainly by A: `vault:ask <question>` (or the plugin **📚 Vault
QA** toggle).

**Expected:** B appears among the sources marked **(graph)** in the terminal, or as a dashed **· graph**
chip in the plugin — i.e. it was surfaced via the link, not pure similarity.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

### T16.04 — Tuning / disable
**Steps:** Set `"hybrid_retrieval": false` in `settings.json`, restart, repeat T16.03; then restore
`true` and try `"hybrid_weights": { "vector": 1.0, "link": 0.5, "tag": 0.3 }`.

**Expected:** Disabled → only vector sources (no `(graph)` markers). Higher link/tag weights → more
graph-surfaced sources.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

### T16.05 — Privacy not weakened
**Steps:** Ensure a `private: true` note is `[[linked]]` from a public note; ask a non-private
question answered by the public note.

**Expected:** The private note is **not** pulled in as a graph neighbour (private notes are excluded
from the graph). If a private note is retrieved by similarity, routing still forces no-train (M11).

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

## Section Summary

| Tests | Pass | Fail | Skip |
|-------|------|------|------|
| 5 | | | |

**Deterministic:** T16.01.

**Overall result:** _______________
