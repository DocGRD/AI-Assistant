# M4 — Intelligent Router + Memory System Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

> **Updated for the M10 router rewrite + M4 automation.** Routing is now
> registry-driven and privacy/task-aware (the old "everything defaults to groq"
> behaviour is gone), and most M4 behaviours now have **automated** tests.
> Run the automated block first; only the ⛺ manual tests need a live session.

## Automated coverage — run these first

```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest \
  tests.test_routing tests.test_memory_episodes
```

| Area | Tests | Module |
|------|-------|--------|
| Routing (T4.01–T4.04) | default→google, private→groq, large→high-volume, candidates-never-routed, health flip, ≥3 floor | `tests/test_routing.py` |
| Memory (T4.05/06/08) | structure created, profile loaded, fact survives a restart | `tests/test_memory_episodes.py` |
| remember: (T4.07/09) | immediate timestamped write, empty is graceful | `tests/test_memory_episodes.py` |
| Episodes (T4.10–T4.15, T4.20) | header, live append, tool/remember/chat lines, footer, second-session divider | `tests/test_memory_episodes.py` |
| Context manager (T4.16–T4.18) | trims over threshold, no-trim when small, report format | `tests/test_memory_episodes.py` |

**⛺ Manual only** (LLM behaviour / process kill): T4.19, T4.21, T4.22.

---

## Section 1 — Token-Aware Routing  *(automated: `tests/test_routing.py`)*

### T4.01 — Small non-private request → the default provider
**Now:** the everyday non-private default is **groq / llama-3.3-70b-versatile** (Google's free tier is
only ~20 req/day, so it's no longer first — it's kept for long-context). 
**Live check:** `verbose on`, ask `What is 2 + 2?` → log shows
`route_order(private=False, high_volume=False) → ['groq', ...]` then `[Router] Sending to: groq`.
**Automated:** `RoutingTests.test_small_default_prefers_groq`.

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

### T4.02 — Large / high-volume request → a high-volume provider
**Now:** large or high-volume turns prefer **cerebras**, then groq's 8B — not google.
**Live check:** load a big `vault:search`, then ask → log shows
`route_order(private=False, high_volume=True) → ['cerebras', ...]` and `Sending to: cerebras`.
**Automated:** `RoutingTests.test_large_longform_prefers_high_volume`.

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

### T4.03 — A failing provider is marked unhealthy and dropped
**Now:** there is no fixed 65-second timer. A provider is marked **unhealthy after 3 consecutive
real-traffic failures** (`UNHEALTHY_THRESHOLD`) and skipped until it recovers; the startup report warns
when fewer than three active providers are healthy (the ≥3 floor).
**Automated:** `RoutingTests.test_failures_mark_unhealthy_and_drop_from_routing`,
`test_floor_drops_below_three_when_two_keys_unhealthy`.

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

### T4.04 — `models` shows the session error log after a real error  *(⛺ live)*
**Steps:** trigger a provider error (bad key / rate limit), then type `models`.
**Expected:** a `Provider errors this session:` section lists the error (not "No errors recorded").
Health flips are covered automatically; this checks the terminal report.

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

### T4.P — Privacy routing  *(new — automated)*
A `private` turn routes only to `trains_on_data = no` providers (**google and NVIDIA excluded**) and
will not hand off to a web AI unless the user opts in.
**Automated:** `RoutingTests.test_private_excludes_trains_on_data_yes`, `test_private_small_prefers_groq`.

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

---

## Section 2 — Memory Manager Startup  *(automated)*

### T4.05 — `AI/Memory/` structure created on first run
**Automated:** `MemoryStructureTests.test_structure_created_on_first_run` (User-Profile.md,
Facts/Learned-Facts.md, Projects/, Episodes/).

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

### T4.06 — `User-Profile.md` is loaded into context
**Automated:** `ContextLoadTests.test_profile_loaded_into_context` (a distinctive line in the profile
appears in `load_context()`). Live: add `My favourite colour is teal.`, restart, ask — answers correctly.

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

---

## Section 3 — `remember:` Command  *(automated)*

### T4.07 — `remember:` saves immediately with a timestamp
**Automated:** `RememberTests.test_remember_writes_immediately_with_timestamp`.

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

### T4.08 — Remembered fact is available next session
**Automated:** `ContextLoadTests.test_remembered_fact_available_next_session` (a fresh MemoryManager
loads it from Learned-Facts.md).

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

### T4.09 — Empty `remember:` is graceful
**Automated:** `RememberTests.test_empty_remember_is_graceful` ("Nothing to remember", nothing written).

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

---

## Section 4 — Episode Logging  *(automated)*

- **T4.10** episode file + header — `EpisodeTests.test_episode_created_with_header`
- **T4.11** live append before close — `test_live_append_is_immediate` (also covers the crash-safety
  *mechanism* behind T4.19: every write is flushed immediately)
- **T4.12 / T4.13 / T4.20** vault-tool line, remember line, chat line with `[provider]` tag —
  `test_vault_and_remember_and_chat_lines`
- **T4.14** session footer on close — `test_footer_on_close`
- **T4.15** second session same day appends with a `---` divider — `test_second_session_appends_with_divider`

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

---

## Section 5 — Context Window Manager  *(automated)*

- **T4.16 / T4.17** trims when history exceeds the safe threshold, and the result is smaller —
  `ContextManagerTests.test_trims_when_over_threshold` (+ `test_no_trim_when_small`)
- **T4.18** `context` report format (`~N tokens in history (N% of <provider> TPM limit), N messages`) —
  `test_report_format`. *Note: the report names the active provider (now usually google), not groq.*

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

---

## Section 6 — Crash Safety  *(⛺ manual — process kill)*

### T4.19 — Hard-kill mid-session preserves prior events
Start, have 2–3 exchanges, force-close the terminal (don't `exit`), open the episode file — all prior
exchanges are present. *(The immediate-flush mechanism this relies on is covered by T4.11.)*

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

---

## Section 7 — Assistant Self-Awareness  *(⛺ manual — LLM behaviour)*

### T4.21 — Reads Project-State when asked about its architecture
Ask: `Can you read your own project state and tell me what milestone we're on?` → it runs
`vault:read AI/System/Project-State.md` and answers from it. **Re-test now:** the new honesty guard
should make it actually read the file rather than fabricate a milestone.

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

### T4.22 — Offers to save important decisions to project memory
Discuss a decision (e.g. "use FastAPI over Flask") → it offers `vault:update AI/Memory/Projects/<name>.md`.

- [ ] ✅ Pass &nbsp; [ ] ❌ Fail &nbsp; [ ] ⏭ Skip

---

## Section Summary

| Category | Count | How |
|----------|-------|-----|
| Automated (routing) | T4.01–T4.04, T4.P | `tests/test_routing.py` |
| Automated (memory/episodes/context) | T4.05–T4.18, T4.20 | `tests/test_memory_episodes.py` |
| Manual (kill / LLM behaviour) | T4.19, T4.21, T4.22 | live session |

**Overall M4 result:** _______________
