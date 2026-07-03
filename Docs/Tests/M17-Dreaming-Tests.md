# M17 — Dreaming & Consolidation Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

Nightly pass turns episodes → durable-fact proposals (forced-private, deduped), archives old episodes,
and compresses long chats. Propose/commit — live memory is never edited without your approval. See
[[Project-State]] M17 and [[User-Guide]].

---

## Section 1 — Automated

### T17.01 — Consolidation unit tests
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_consolidation -v`
**Expected:** Pass — extraction is forced private; the watermark prevents re-processing; the in-progress
day is skipped; near-duplicates are suppressed; archival moves files + writes a digest; `--apply` appends
to `Learned-Facts`.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T17.02 — Context summarization + scheduler decision
**Steps:** `… -m unittest tests.test_memory_episodes tests.test_scheduler -v`
**Expected:** Pass — `context_summarization` replaces a trimmed span with a `[Summary …]` block and falls
back to trim on failure; `consolidate_due` fires once per night.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

## Section 2 — Live (box with episodes)

### T17.03 — One-shot consolidation writes a proposal
**Steps:** On the box: `python -m assistant_core --consolidate`.
**Expected:** Prints `days=… new=… proposal=AI/Memory/proposed/consolidation-YYYY-MM-DD.md`. The proposal
lists candidate facts as `- [ ]` checkboxes. **`Learned-Facts.md` is unchanged.**

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T17.04 — Plugin Memory-review panel
**Steps:** With a proposal present, open the AI Assistant sidebar. In the 🧠 Memory review panel, untick a
fact, click **Save selected**.
**Expected:** The ticked facts are appended to `Learned-Facts.md`; the proposal note is removed; unticked
facts are not saved.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T17.05 — `--apply` merges directly
**Steps:** `python -m assistant_core --consolidate --apply`.
**Expected:** New facts are appended to `Learned-Facts.md` (tagged `[YYYY-MM-DD consolidated]`).

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T17.06 — Archival
**Steps:** With episodes older than `episode_archive_days` (default 30), run `--consolidate`.
**Expected:** Old daily episodes move to `AI/Memory/Episodes/Archive/`; a monthly `digest-YYYY-MM.md`
lists them. The current day is untouched.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T17.07 — Nightly automatic run
**Steps:** Leave the service running overnight with `auto_consolidate_enabled: true`.
**Expected:** Around `auto_consolidate_hour` (default 4), a proposal appears without manual action; the log
shows `[Scheduler] Running nightly memory consolidation`.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________
