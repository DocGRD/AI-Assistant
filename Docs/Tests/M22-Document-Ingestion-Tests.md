# M22 — Document Ingestion Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

`vault:ingest <file>` extracts a PDF/EPUB/DOCX/txt into a searchable, AI-derived `AI/Library/<slug>.md`
with per-page provenance anchors, indexed for Vault QA. Optional graph feed. Original file untouched.
See [[Project-State]] M22 and [[User-Guide]].

---

## Section 1 — Automated

### T22.01 — Ingestion unit tests
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_ingest -v`
**Expected:** Pass — `.txt`/`.md` extract with no dependency; missing/unsupported files are graceful; a
multi-page ingest writes `## Page N` anchors + frontmatter; an extraction error is reported (no note);
real `.md` end-to-end.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

## Section 2 — Live (box)

### T22.02 — Ingest a PDF
**Steps:** `pip install pypdf` (once), then `vault:ingest C:/path/to/document.pdf`.
**Expected:** Reports "Ingested pdf (N pages, C chars) → `AI/Library/<date>-<slug>.md`". The note has
frontmatter `ai-derived: ingested-document`, a `# Title`, and `## Page N` sections with the text.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T22.03 — Ingested doc answers in Vault QA
**Steps:** After ingest (index refreshed), `vault:ask <a question the document answers>`.
**Expected:** The answer draws on the ingested doc and cites the `AI/Library/…` note.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T22.04 — EPUB / DOCX
**Steps:** `pip install ebooklib python-docx`; `vault:ingest book.epub`; `vault:ingest report.docx`.
**Expected:** EPUB → one section per chapter; DOCX → sections split at Heading paragraphs. Both saved +
indexed.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T22.05 — Graceful without the library
**Steps:** Without `pypdf` installed, `vault:ingest something.pdf`.
**Expected:** Clear message "pypdf not installed (pip install pypdf)"; no crash, no note written.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T22.07 — 📎 Ingest via the paperclip
**Steps:** In the sidebar, click the **📎** paperclip and pick a document (PDF/EPUB/Word/text) already in
the vault.
**Expected:** It runs `vault:ingest` on that file and reports the new `AI/Library/` note. (External files:
copy into the vault first, then attach.)

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T22.06 — Original untouched
**Steps:** Check the source file after ingest.
**Expected:** The original document is unchanged; only the `AI/Library/` note was created.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________
