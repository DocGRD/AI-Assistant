# PR draft: Probe-before-active for `vault:discover-providers`

**Goal:** Discovery should only mark a model `active` when a live chat completion succeeds (or when merging a previously curated active row that still probes OK). New `/models` entries default to `candidate`.

**Why:** Raw discovery auto-activates every new chat id. That flooded the router with untested Google/NVIDIA rows, kept the `models/` prefix on Google ids, and treated “listed on `/models`” as “works on free tier.”

---

## Behaviour changes

### 1. Normalize Google model ids on write
In `registry_proposer.py`, when emitting `model_id` for the proposal table, store the **bare** id (strip leading `models/`). Matching already uses `_norm_id`; the written cell should too.

### 2. New models → `candidate`, not `active`
Change:

```python
status = getattr(prev, "status", None) or "active"
```

to:

```python
status = getattr(prev, "status", None) or "candidate"
```

Notes for new rows: `discovered from /models — candidate until probed`.

### 3. Optional probe pass (default on for manual discover)
After building the candidate list (or during it), for each chat model that would be `active` **or** is newly discovered and `provider in {groq, cerebras, google}` (configurable):

1. POST `{base}/chat/completions` with  
   `{"model": <bare_id>, "messages": [{"role":"user","content":"ping"}], "max_tokens": 16}`  
   using the provider key from config.
2. **200 + non-empty assistant content** → may set `status=active`, note `probed OK YYYY-MM-DD`.
3. **404 / model_not_found / decommissioned** → `status=deprecated` or keep candidate with note `probe failed: …`.
4. **401 / 403** → provider-level error; don’t mark models active.
5. **429** → treat as “exists but limited”; leave **candidate** (or active if previously curated active) with note `probe rate-limited`.
6. Timeout / 5xx → candidate, note failure.

**Caps:**
- Max probes per run (e.g. 30) so NVIDIA dumps don’t hammer the API.
- Prefer probing: previously active rows first, then new groq/cerebras/google, skip bulk nvidia unless `probe_nvidia: true`.
- Parallelism: low (2–3) to respect RPM.

### 4. Never auto-active NVIDIA (and similar)
Policy table:

| provider | new model default | auto-promote on probe |
|----------|-------------------|------------------------|
| groq | candidate | yes if probe OK |
| cerebras | candidate | yes if probe OK |
| google | candidate | yes if probe OK (still `trains_on_data=yes`) |
| nvidia | candidate | **no** (probe optional; stay candidate) |

### 5. Config knobs (`settings.json`)
```json
{
  "discovery_probe_enabled": true,
  "discovery_probe_max": 30,
  "discovery_probe_providers": ["groq", "cerebras", "google"],
  "discovery_auto_active_on_probe": true
}
```

Weekly scheduler can use the same job with probe enabled or a lighter “list only” mode if probes burn free quota — document the tradeoff.

### 6. Proposal summary in the reply
After discover, human-readable summary:

```text
Discovered 120 models. Probed 18.
  active (probe OK): 7
  candidate (unprobed or failed): 90
  specialized: 23
  provider errors: none
Wrote AI/System/Provider-Registry-proposed.md
```

### 7. Tests
- Unit: `_norm_id` / written Google ids never have `models/` prefix.
- Unit: new model without prev → candidate when probe disabled.
- Unit: probe 200 → active; probe 404 → not active.
- Integration: mock `list_fn` + mock HTTP for completions.

---

## Files likely touched

| File | Change |
|------|--------|
| `assistant_core/providers/registry_proposer.py` | default candidate; normalize written ids; optional probe results merge |
| `assistant_core/providers/discovery_job.py` | call probe step; richer message |
| `assistant_core/providers/model_probe.py` (new) | minimal completion probe helper |
| `tests/test_registry_proposer.py` / discovery tests | cover defaults + probe |
| `Docs/Help/Commands.md` / Provider-Registry docs | document probe-before-active |

---

## Out of scope (follow-ups)

- Fetching RPD/TPM from dashboards (still not on `/models`)
- Cha
... 