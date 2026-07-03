# M15 — Self-Testing + Muscle-Memory Scripts (propose/commit) Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

`vault:test` runs the suite; the agent only *proposes* scripts (to `AI/Scripts/proposed/`), you approve
them (move up), and run with `vault:run-script`. Strict allow-list, no autonomous execution. See
[[Project-State]] M15 and [[User-Guide]].

---

## Section 1 — Automated

### T15.01 — Scripts runner unit tests
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_scripts_runner -v`
**Expected:** Pass — proposed scripts are not runnable; only an approved (moved-up) script in
`AI/Scripts/` runs; unknown/blocked names are refused.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

## Section 2 — Live (terminal or plugin)

### T15.02 — `vault:test` runs the suite
**Steps:** In the terminal: `vault:test`.
**Expected:** Prints `[Self-test] Running the unittest suite…`, a short tail, then
`[Self-test] PASSED` (return code 0). An episode is logged. No stray error lines.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T15.03 — Agent proposes a script (never executes)
**Steps:** Ask the assistant to "write a script that lists my largest notes."
**Expected:** It writes to `AI/Scripts/proposed/<name>.py` and tells you to review + approve. Nothing runs.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T15.04 — Approve + run
**Steps:** Move the reviewed script from `AI/Scripts/proposed/` up to `AI/Scripts/`, then
`vault:run-script <name>`.
**Expected:** The approved script runs and prints its output. A script still in `proposed/` is refused.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T15.05 — Unknown script refused
**Steps:** `vault:run-script does-not-exist`.
**Expected:** Clear "not found / not approved" message; nothing executes.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________
