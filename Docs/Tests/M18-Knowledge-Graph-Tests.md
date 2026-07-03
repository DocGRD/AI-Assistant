# M18 — Semantic Knowledge Graph + Guides Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

Entity/relation extraction → linked Markdown under `AI/Graph/Entities/` (Obsidian graph view renders it),
a plugin Graph viewer + entity browser, `vault:guide <topic>` cited overviews, and alias-merge. Private
entities honour `graph_include_private`. See [[Project-State]] M18 and [[User-Guide]].

---

## Section 1 — Automated

### T18.01 — Graph unit tests
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_graph -v`
**Expected:** Pass — triple parse/clean/cap, forced-private extraction, merge_triples idempotent +
sticky-private, subgraph BFS depth + private-neighbour hiding, `list_entities` by degree, alias
suggest/merge, and `build_guide` cited answer.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

## Section 2 — Live (box)

### T18.02 — Build the graph for one note
**Steps:** `vault:graph <a content-rich note path>` (terminal or plugin).
**Expected:** Reports N relationships; entity notes appear under `AI/Graph/Entities/` with a `## Relations`
(`[[links]]`) and `## Source notes` section.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T18.03 — Whole-vault incremental build
**Steps:** `python -m assistant_core --build-graph --limit 50` (repeat until `processed 0`).
**Expected:** Processes changed real-user notes only (derived `AI/` trees skipped); re-runs skip unchanged
notes.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T18.04 — Plugin Graph viewer + entity browser
**Steps:** Sidebar → **Graph** button. Click **Browse all** (or leave the box empty).
**Expected:** A list of entities (most-connected first) appears; clicking one draws its subgraph; clicking
a neighbour recenters; clicking the centre opens its source note. Obsidian's own graph view also shows
`AI/Graph/Entities`.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T18.05 — `vault:guide` cited overview
**Steps:** `vault:guide <an entity name>`.
**Expected:** A concise, cited (`[[note]]`) overview assembled from the entity's cluster + source notes.
No fabricated links.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T18.06 — Alias merge
**Steps:** `vault:graph-merge <Canonical Name> -> <Alias Name>`.
**Expected:** The alias's relations/sources merge into the canonical; incoming `[[Alias]]` links repoint;
the alias note is removed; the alias is recorded in the canonical's `aliases:` frontmatter.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T18.07 — Private entities hidden by default
**Steps:** Graph a note with `private: true`; open the Graph viewer with `graph_include_private: false`.
**Expected:** Its entities do not appear. Set `graph_include_private: true` (restart) → they appear.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________
