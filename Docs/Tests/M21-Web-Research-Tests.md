# M21 — Web-Capable Research Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

`vault:webresearch <question>` searches the web (config-driven, free-first), fetches the top pages, writes
a cited synthesis + the verbatim sources under `AI/Research/<date>-<slug>/`, and links real related notes.
**Private turns never touch the web.** See [[Project-State]] M21 and [[User-Guide]].

---

## Section 1 — Automated

### T21.01 — Web search/fetch/research unit tests
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_web -v`
**Expected:** Pass — provider fall-through skips unconfigured + on failure (keyless-first order); fetch
html→text is failure-safe; the orchestrator saves a summary + verbatim sources + citations; **a private
turn writes nothing**; disabled/no-results are handled.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

## Section 2 — Live (needs internet)

### T21.02 — Autonomous web research (keyless)
**Steps:** `vault:webresearch how do rocket mass heaters work` (no API keys set → DuckDuckGo).
**Expected:** Reports "saved to `AI/Research/<date>-<slug>/Summary.md` (N sources)". `Summary.md` has a
cited synthesis (`[n]`) + a Sources list; each `Source-N.md` holds a fetched page verbatim with its URL.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T21.03 — Privacy hard-block
**Steps:** Turn on 🔒 Private in the plugin, then `vault:webresearch <anything>`.
**Expected:** Refused with "web research is disabled for private turns"; **nothing is written**; no network
request is made.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T21.04 — Add a search provider by key
**Steps:** Set `tavily_api_key` (or `brave_api_key`) in settings, restart, `vault:webresearch <query>`.
**Expected:** That provider is used (it's earlier/available in `web_search_order`); results still saved
with citations. Removing all keys falls back to keyless DuckDuckGo.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T21.05 — Cited synthesis only cites fetched pages
**Steps:** Open the resulting `Summary.md`.
**Expected:** Every `[n]` maps to a fetched Source; no invented URLs.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________
