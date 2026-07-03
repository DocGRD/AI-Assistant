# M20 — Agent Planner Robustness + Research Round-Trip Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

Deliverable tools end the turn (no runaway); an externalized `TaskLedger` (→ `AI/System/Task-State.md`)
keeps continuity across provider switches; the research paste-back saves verbatim, then adds a
non-agentic summary + real related notes + a short title. See [[Project-State]] M20 and [[User-Guide]].

---

## Section 1 — Automated

### T20.01 — Agent loop + ledger + round-trip unit tests
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_agent_loop tests.test_task_ledger tests.test_research_roundtrip -v`
**Expected:** Pass — a deliverable tool ends the turn; `extract_vault_commands` keeps multi-paragraph
bodies (no blank-line truncation); the ledger injects/accumulates + flags a provider switch + persists;
research summary is one non-agentic call; related notes are real or none.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

## Section 2 — Live (plugin/terminal)

### T20.02 — `vault:research` is a deliverable, not a runaway
**Steps:** `vault:research How do rocket mass heaters work?`
**Expected:** Prints the research prompt and **stops** — it does not keep issuing commands or research the
topic itself.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T20.03 — Paste-back saves verbatim + summarises
**Steps:** Paste a web-AI answer back (plugin **Submit response**, or terminal `---end`).
**Expected:** The full research is saved verbatim to `AI/Research/<date>-<short-title>.md`; a 2–3 sentence
summary is shown; a `## Related notes` section links only **real** vault notes (or none). No fabricated
`[[links]]`, no loop.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T20.04 — Task-State scratchpad
**Steps:** Ask a multi-step vault question, then open `AI/System/Task-State.md`.
**Expected:** It shows the goal and per-step `✓/✗` checkpoints; status ends `done`. If the service is
killed mid-task, the file shows where it stopped.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T20.05 — Multi-paragraph note bodies aren't truncated
**Steps:** Have the assistant create/update a note with several paragraphs.
**Expected:** The whole body is written — not just the first line/heading.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________
