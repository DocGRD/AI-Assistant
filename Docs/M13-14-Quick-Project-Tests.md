# M13/M14 — Quick Commands, Prompt Library & Project Awareness Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

See [[User-Guide]] §6.9. Live tests use the plugin + running service.

---

## Section 1 — Automated (deterministic)

### T13.01 — Prompt seeding + project injection unit tests
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_memory tests.test_chat_context -v`

**Expected:** Pass — `seed_prompts` seeds `AI/Prompts/` when empty and never clobbers existing prompts;
a note with `project: <name>` injects `AI/Memory/Projects/<name>.md` into the chat context.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 2 — Quick commands (M13)

### T13.02 — Chat quick actions
**Steps:** Open a note; click **Summarize** (then **Key points**, **Action items**).

**Expected:** Each returns an answer about the active note.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T13.03 — Edit quick actions
**Steps:** Select text in a note; click **Fix grammar** (then **Improve**).

**Expected:** A proposed-edit dialog appears for the selection; **Replace** applies it. With nothing
selected, a notice asks you to select text.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T13.04 — Saved prompts
**Steps:** Click **Prompts…**; pick "Summarize" (with text selected); also try one using `{{note}}`.

**Expected:** `AI/Prompts/` is listed; `{{selection}}`/`{{note}}` are substituted and the prompt runs.
Adding a new `.md` to `AI/Prompts/` makes it appear in the picker.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T13.05 — Command palette
**Steps:** Run "Summarize active note" and "Run a saved prompt" from the command palette.

**Expected:** Both work and focus the sidebar.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 3 — Project awareness (M14)

### T13.06 — `project:` frontmatter injects project memory
**Steps:** Add `project: <name>` to a note (with `AI/Memory/Projects/<name>.md` present); ask a
question about that project while the note is active.

**Expected:** The answer reflects the project memory's content; logs show "Project memory injected".

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 4 — Self-test & scripts (M15)

### T15.01 — Script-runner safety (deterministic)
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_scripts_runner -v`

**Expected:** Pass — invalid/traversal names rejected; a script still in `proposed/` won't run; an
approved `AI/Scripts/*.py` runs; a nonzero exit is reported as failure.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T15.02 — `vault:test` self-check (live)
**Steps:** `python assistant.py --terminal` → `vault:test`.

**Expected:** Runs the unittest suite and prints `PASSED` (or the failing tail).

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T15.03 — Propose → approve → run (live)
**Steps:** Have the assistant write a script to `AI/Scripts/proposed/hello.py`; try `vault:run-script
hello` (should refuse); move it to `AI/Scripts/hello.py`; `vault:run-script hello`.

**Expected:** Refused while in `proposed/`; runs once approved (moved up); `../`-style names rejected.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section Summary

| Tests | Pass | Fail | Skip |
|-------|------|------|------|
| 9 | | | |

**Deterministic:** T13.01, T15.01.

**Overall result:** _______________
