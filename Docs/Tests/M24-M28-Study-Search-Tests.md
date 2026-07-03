# M24–M28 — Scripture, Provenance, Search, Audio & Study Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

Covers Scripture Intelligence (M24), Provenance & Citations (M25), Structured & Exact Search (M26),
Audio Transcription (M27), and Study Reinforcement (M28). See [[Project-State]] and [[User-Guide]].

---

## Section 1 — Automated

### T-AUTO — Unit tests
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_scripture tests.test_provenance tests.test_query tests.test_audio tests.test_study -v`
**Expected:** Pass — ref parsing/overlap + passage guide; provenance source scoring + unsourced-claim
flag; structured-search predicates + NEAR; audio transcription sidecar (injected transcriber); flashcard
parse/generate + SM-2 scheduling.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

## Section 2 — Live

### T24.01 — Passage guide (M24)
**Steps:** `vault:passage 1 John 2:18-20` (with sermon/study notes on that passage).
**Expected:** A cited overview drawn only from notes that reference an **overlapping** passage; a list of
those notes. `vault:passage not-a-ref` → a clear "not a recognised reference" message.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T25.01 — Provenance audit (M25)
**Steps:** `vault:sources <a claim already covered by a note>` (e.g. a fact you know is written in a
note); then `vault:sources <a claim nothing in the vault covers>`.
**Expected:** The first reports **sourced** and lists the supporting note(s), best match first, with the
overlap terms; the second reports **unsourced** (no note meets the term-overlap threshold). Episode logs
are never offered as a source.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T26.01 — Structured search (M26)
**Steps:** `vault:query tag:sermon "the last hour"` ; `vault:query path:"06 - Projects" fm:project=camping` ;
`vault:query ESV NEAR/3 antichrist`.
**Expected:** Only notes matching **all** predicates; NEAR respects the word distance; episode logs
excluded.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T27.01 — Transcribe audio (M27)
**Steps:** `pip install faster-whisper` (once); put a sermon audio file in the vault;
`vault:transcribe <audio path>`.
**Expected:** A local transcript at `AI/Derived/<name>.transcript.md` (audio never uploaded); it then
answers in Vault QA. Without the library → a clear "install faster-whisper" message, no crash.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T28.01 — Flashcards + review (M28)
**Steps:** `vault:cards <a study note>`, then `vault:review`.
**Expected:** `vault:cards` reports N cards added (to `AI/Review/deck.json`); `vault:review` lists the
cards due today. Grading a card (via the API `review()`) pushes its next due date out (SM-2).

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________
