# M10 — Provider Registry + Privacy/Task Routing + Health Floor Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

Proves the Milestone 10 changes: registry-driven per-model routing, privacy-first + task-aware
selection, the self-updating registry tracker, and health tracking with a ≥3-provider floor.
See [[User-Guide]] for usage and [[Provider-Registry]] for the live data.

> **Two kinds of test below.** **Deterministic** tests run offline with no API calls (they prove the
> routing *logic* and never burn free-tier quota). **Live** tests use real API calls — run those
> sparingly (Google's free tier is ~1,500/day). Run all commands from the repo root with the venv
> active; prefix Python with `PYTHONIOENCODING=utf-8` on Windows.

---

## Section 1 — Automated checks (deterministic, no network)

### T10.01 — Unit tests pass
**Steps:**
1. `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_routing tests.test_registry_loader -v`

**Expected:** `Ran 12 tests ... OK`. Covers privacy filter, task shape, candidates-never-chosen,
health flip, the ≥3 floor, registry parsing, and a broken row being skipped.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.02 — Registry loads and a malformed row is skipped, not fatal
**Steps:**
1. `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_registry_loader.RegistryLoaderTests.test_broken_row_skipped_and_reported -v`

**Expected:** Pass. A row with a non-integer limit is dropped and reported in `loader.skipped`; the
valid rows still load.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 2 — Startup registry report

### T10.03 — Startup prints the live registry table
**Steps:**
1. `python assistant.py --terminal`
2. Read the **Provider Registry** block in the startup output.

**Expected:** A table with a *(updated: …)* date listing route keys `groq`, `google`,
`groq:llama-3.1-8b-instant`, `cerebras` as `active`, and `nvidia` / `openrouter` as
`candidate - registered, not routed`. Each row shows its `trains_on_data` value.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.04 — Floor warning when fewer than 3 providers are active/healthy
**Steps:**
1. With **no** `cerebras_api_key` set, start `python assistant.py --terminal`.

**Expected:** Startup report shows Cerebras as `active - no key (not built)` and prints a
`⚠ Floor: … healthy active provider(s) … target ≥3` warning. (Adding a real `cerebras_api_key`
removes the warning.)

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 3 — Per-model routing & candidates

### T10.05 — One provider is built per active row
**Steps (deterministic):**
```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import tempfile; from providers.provider_router import ProviderRouter; r=ProviderRouter({'vault_path':tempfile.mkdtemp(),'groq_api_key':'x','google_api_key':'x','cerebras_api_key':'x'}); print(sorted(r.available_models))"
```

**Expected:** `['cerebras', 'google', 'groq', 'groq:llama-3.1-8b-instant']` — the 8B model is its own
route target, and candidates are absent.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.06 — NVIDIA and OpenRouter are registered but NEVER chosen
**Steps (deterministic):**
```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import tempfile; from providers.model_registry import ModelRegistry; reg=ModelRegistry({'vault_path':tempfile.mkdtemp()}); av=['groq','google','cerebras','groq:llama-3.1-8b-instant','nvidia','openrouter']; print('nvidia/openrouter in order:', any(p in reg.route_order(av) for p in ('nvidia','openrouter')))"
```

**Expected:** `nvidia/openrouter in order: False` — even when offered as available, their
`candidate` status keeps them out of every route order.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.07 — Cerebras is reachable (live)
**Steps:**
1. Put a real `cerebras_api_key` in `settings.json`.
2. `python assistant.py --terminal` → `/use cerebras` → ask `Say hello in one word.`

**Expected:** `Assistant [cerebras]: …` — a real reply via the Cerebras endpoint.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 4 — Privacy routing

### T10.08 — Private NEVER selects Google (deterministic)
**Steps:**
```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import tempfile; from providers.model_registry import ModelRegistry; reg=ModelRegistry({'vault_path':tempfile.mkdtemp()}); av=['groq','google','cerebras','groq:llama-3.1-8b-instant']; print('private order:', reg.route_order(av, private=True))"
```

**Expected:** `private order: ['groq', 'cerebras', 'groq:llama-3.1-8b-instant']` — **no `google`**
(it trains on data). Non-private would include google first.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.09 — `private on` excludes Google in the terminal (live)
**Steps:**
1. `python assistant.py --terminal` → `verbose on` → `private on`
2. Ask a short question.

**Expected:** `[Private ON …]` confirmation; the `[Router] route_order(private=True …)` log shows no
google, and the reply comes from `groq` (or cerebras), never `google`.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.10 — Private does not hand off to web AI without opt-in
**Steps:**
1. In terminal: `private on`, `allow-webui off`, then `/use google` and ask a question (forces the
   privacy-blocked path), or simulate all no-train providers failing.

**Expected:** No web handoff happens; you get an error explaining to type `allow-webui on` and
resend. With `allow-webui on`, a handoff is offered.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.11 — Note frontmatter `private: true` routes privately (watcher)
**Steps:**
1. Create a note with `assistant-status: pending`, `assistant-request: …`, `private: true`.
2. Let the watcher process it (or run headless).

**Expected:** The response is produced by a `trains_on_data=no` provider; Google is never used. If
all fail, the note's error section explains the `allow-webui: true` opt-in.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 5 — Task-aware selection

### T10.12 — Small default request prefers Google
**Steps (deterministic):**
```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import tempfile; from providers.model_registry import ModelRegistry; reg=ModelRegistry({'vault_path':tempfile.mkdtemp()}); av=['groq','google','cerebras','groq:llama-3.1-8b-instant']; print('small:', reg.route_order(av, est_tokens=200, response_tokens=500)[0])"
```

**Expected:** `small: google` — the non-private default leads with Gemini.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.13 — Large long-form request prefers a high-volume provider
**Steps (deterministic):**
```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import tempfile; from providers.model_registry import ModelRegistry; reg=ModelRegistry({'vault_path':tempfile.mkdtemp()}); av=['groq','google','cerebras','groq:llama-3.1-8b-instant']; print('large:', reg.route_order(av, est_tokens=20000, response_tokens=2048, long_form=True))"
```

**Expected:** First entry is `cerebras` (volume/batch). The small-TPM Groq models drop out on the
size check, leaving cerebras ahead of google.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.14 — Private + small prefers Groq
**Steps (deterministic):**
```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import tempfile; from providers.model_registry import ModelRegistry; reg=ModelRegistry({'vault_path':tempfile.mkdtemp()}); av=['groq','google','cerebras','groq:llama-3.1-8b-instant']; print('private small:', reg.route_order(av, private=True, est_tokens=200, response_tokens=500)[0])"
```

**Expected:** `private small: groq`.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 6 — Health floor

### T10.15 — Repeated failures mark a provider unhealthy and drop it
**Steps (deterministic):**
```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import tempfile; from providers.model_registry import ModelRegistry; reg=ModelRegistry({'vault_path':tempfile.mkdtemp()}); av=['groq','google','cerebras','groq:llama-3.1-8b-instant']; [reg.error_log.record('google','other',0) for _ in range(3)]; print('healthy:', reg.error_log.is_healthy('google'), '| order:', reg.route_order(av))"
```

**Expected:** `healthy: False` and `google` is **absent** from the order. (A later
`record_success('google')` restores it — covered by the unit test.)

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.16 — Unhealthy flag and floor warning are raised
**Steps (deterministic):**
```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import tempfile; from providers.provider_router import ProviderRouter; r=ProviderRouter({'vault_path':tempfile.mkdtemp(),'groq_api_key':'x','google_api_key':'x','cerebras_api_key':'x'}); [r._record_failure('google','other',100) for _ in range(3)]"
```

**Expected:** Prints `⚠ Provider 'google' marked UNHEALTHY …` at the third failure, plus a
`⚠ Provider floor breached …` line once healthy distinct providers drop below 3.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.17 — Health comes only from real traffic (no probing)
**Steps:** Review `SessionErrorLog`/router — confirm health changes only inside `generate()`
(success → `record_success`, failure → `record`). There is no background ping/health-check thread.

**Expected:** No code path pings providers to test them; low-RPD providers (Google) are never probed.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 7 — Self-updating registry (propose / commit)

### T10.18 — Propose writes a proposal WITHOUT touching the live registry
**Steps:**
1. Set `provider_source_url` to a source (a local `file://…json` or `…md` works for testing).
2. Terminal: `vault:update-providers`

**Expected:** A diff is printed and `AI/System/Provider-Registry-proposed.md` is created;
`AI/System/Provider-Registry.md` is **byte-for-byte unchanged**. (Deterministic equivalent: the
propose/apply flow in the implementation notes leaves the registry hash identical after propose.)

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.19 — Apply commits the proposal
**Steps:**
1. After T10.18, run `vault:update-providers apply`.

**Expected:** `Provider-Registry.md` now matches the proposed table; the proposed note is consumed
(deleted). Restarting the assistant routes on the new values.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.20 — No source configured falls back to a research prompt
**Steps:**
1. Clear `provider_source_url` (empty), then `vault:update-providers`.

**Expected:** No crash; the tool returns a `vault:research`-style prompt to paste into a web AI, and
does **not** modify the registry.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 8 — Regression (nothing else broke)

### T10.21 — Groq and Google still answer (live)
**Steps:**
1. `python assistant.py --terminal` → `/use groq` → ask a question → `/use google` → ask again.

**Expected:** `Assistant [groq]: …` then `Assistant [google]: …`. Both reply through the generic
adapter; the `[groq]` / `[google]` tags are unchanged from before M10.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.22 — Service still starts headless
**Steps:**
1. `python assistant.py --headless` (or `python assistant.py` with no TTY); then `curl http://127.0.0.1:8765/shutdown`.

**Expected:** Starts cleanly (startup report renders, watcher + HTTP server up), answers `/status`,
and shuts down on `/shutdown` or Ctrl+C with no traceback.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.23 — `status` / `models` reflect the registry
**Steps:**
1. In terminal: `status`, then `models`.

**Expected:** `status` lists groq/google/cerebras/webui with ✓ and shows `Private mode`; `models`
lists the registry-loaded specs (including the 8B model and candidates).

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section 9 — Plugin (registry-driven dropdown + privacy)

> Rebuild the plugin (`npm run build` in `obsidian-plugin/`) and copy `main.js` + `styles.css` to
> `<vault>/.obsidian/plugins/ai-assistant/`, then reload the plugin in Obsidian.

### T10.24 — Provider dropdown is populated from the registry
**Steps:**
1. With the service running, open the AI Assistant sidebar.
2. Open the **Provider** dropdown.

**Expected:** It lists Auto + every **active** provider the service loaded (Groq, Gemini, Cerebras,
Groq · llama-3.1-8b-instant, Web UI) — i.e. the keys from `/status`. Candidates (NVIDIA/OpenRouter)
do **not** appear. Adding an active row to `Provider-Registry.md` and restarting the service makes it
appear here with no plugin edit.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

### T10.25 — Private toggle routes privately from the plugin
**Steps:**
1. Click the **🔒 Private** toggle (turns green), then send a message.

**Expected:** The reply never comes from Gemini. If all privacy-safe providers are down, a
"Send via Web AI anyway" button appears instead of a silent handoff; clicking it retries with the
opt-in. (The `/chat` body carries `private: true` and `allow_webui_on_private`.)

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:**
_______________

---

## Section Summary

| Tests | Pass | Fail | Skip |
|-------|------|------|------|
| 25 | | | |

**Deterministic (no API) tests:** T10.01, T10.02, T10.05, T10.06, T10.08, T10.12–T10.16 — these
should pass on any machine with the repo + venv, no keys required.

**Overall M10 result:** _______________

**Open bugs:**

_______________
