# Project-State.md — M10 revision

Drop-in replacement for **Milestone 10**, plus a short patch-list for the rest of the doc.
Reflects the four decisions: (1) generic OpenAI-compatible provider, (2) private-flag routing,
(3) propose/commit auto-update from a machine-readable source, (4) Gemini as default.

---

## Patch-list (apply these small edits elsewhere in Project-State.md)

1. **`## Current Provider Table`** — replace the body with the corrected mid-2026 numbers
   (see `Provider-Registry.md`): Google `gemini-2.5-flash` ~1,500 RPD / 250K TPM (default);
   Groq `llama-3.3-70b-versatile` ~1,000 RPD / 12K TPM; Groq `llama-3.1-8b-instant` ~14,400 RPD;
   Cerebras `llama-3.3-70b` ~1M tokens/day. Add a line: *"Full live list and routing intent:
   `AI/System/Provider-Registry.md`."*

2. **`## Standing Design Principles`** — add two principles:
   - **Privacy is a routing input.** Notes flagged `private` are sent only to providers whose
     registry `trains_on_data = no`. The router filters the candidate set before selecting.
   - **Adding a provider is a Markdown edit.** A single generic OpenAI-compatible adapter is
     instantiated per active row in `Provider-Registry.md`. No Python file per provider.

3. **`### Contract 2 — Adding a New Provider`** — append a note: *"Most providers are
   OpenAI-compatible and need no new class — add a row to `Provider-Registry.md` instead.
   Write a bespoke `BaseProvider` subclass only for genuinely non-compatible APIs."*

---

## Milestone 10 — Provider Registry + Free Endpoint Tracker  *(revised)*

**Rationale:** Free endpoints change constantly — limits shift, models get added and deprecated.
Hard-coding specs means the router runs on stale data. (Confirmed live: Groq's 70B daily cap fell
from 14,400 to ~1,000, while Google's free Flash rose to ~1,500/day — our hard-coded values had
both wrong, in opposite directions.) This milestone makes provider knowledge a living vault
document the assistant can update itself, and collapses provider integration to a single adapter.

**Goal:** `AI/System/Provider-Registry.md` is the single source of truth. The router reads it at
startup, instantiates one generic provider per active row, routes by task and by privacy, and keeps
a floor of ≥3 healthy providers.

### 10.1 — Provider Registry Vault File
`AI/System/Provider-Registry.md` — structured Markdown table. Columns: `provider_key`, `base_url`,
`model_id`, `context_window`, `tpm`, `rpm`, `rpd`, `tpd`, `trains_on_data`, `status`, `strengths`,
`notes`. API key per row is read from settings as `<provider_key>_api_key`. See the seeded file for
the format and current data. Statuses: `active` (routed), `candidate` (registered, not routed until
tested), `deprecated`.

### 10.2 — Generic OpenAI-Compatible Provider  *(the keystone change)*
New module: `providers/openai_compatible_provider.py` — `OpenAICompatibleProvider(BaseProvider)`.
Constructed from a registry row + the matching API key. Uses the `openai` SDK with
`base_url=<row.base_url>`. Implements `generate()` per Contract 2; maps HTTP 401→`ProviderAuthError`,
429→`ProviderRateLimitError`, other failures→`ProviderError`. This single class replaces the planned
per-provider files (no separate `nvidia_provider.py`).

### 10.3 — Registry Loader
New module: `providers/registry_loader.py` — `RegistryLoader`.
- `load() -> list[ModelSpec]` — parse the table; bad rows are **skipped and reported**, never fatal.
- `seed() -> None` — write the default registry if the file is missing.
`ModelRegistry.__init__()` calls `load()` and merges over the hard-coded fallbacks (file wins).
The router builds one `OpenAICompatibleProvider` per `active` row.

### 10.4 — Task- and Privacy-Aware Routing
- **Privacy filter first:** if the request is flagged `private`, drop all rows where
  `trains_on_data != "no"` before any other selection.
- **Task match:** use `strengths` tags + request shape (size, tool-use need, long-form) to pick.
  Default order: `google/gemini-2.5-flash` (non-private) → `groq/llama-3.3-70b` → `cerebras` →
  `groq/llama-3.1-8b-instant`. Private default starts at Groq/Cerebras.
- **Health floor:** track success/failure from real traffic (extend `SessionErrorLog`). A provider
  that fails is flagged in the startup report and skipped until it recovers. **Never actively probe
  low-RPD providers** (e.g. Google) — probing burns the daily budget. Maintain ≥3 `active` providers.

### 10.5 — Provider Tracker Tool  *(propose/commit)*
New tool: `tools/provider_tracker.py` — `ProviderTrackerTool`. Command: `vault:update-providers [provider]`.
1. Fetch a **known machine-readable source** of free-tier specs (a maintained community list) directly
   over HTTP — this is a plain fetch, not an AI call, so it is free and needs no web AI.
2. Diff it against the current registry; write the proposed changes into a review note
   (`AI/System/Provider-Registry-proposed.md`) for the user to approve — **never auto-overwrites**.
3. `vault:update-providers apply` commits the approved rows into `Provider-Registry.md`.
4. Fallback for ambiguous/unparseable rows: emit a `vault:research` prompt for the web-AI handoff,
   then integrate the pasted result the same way.

### 10.6 — Startup Registry Report
`run_startup_diagnostics()` prints the table from the live registry: last-updated date, active vs
candidate, and any provider currently flagged unhealthy. Warns if fewer than 3 active providers.

### M10 Deliverables
- `providers/openai_compatible_provider.py` — new (generic adapter)
- `providers/registry_loader.py` — new
- `tools/provider_tracker.py` — new
- `providers/model_registry.py` — call `RegistryLoader.load()`, merge over fallbacks
- `providers/provider_router.py` — instantiate generic provider per active row; privacy + task routing; health floor
- `memory/memory_manager.py` — `seed_provider_registry()`
- `assistant.py` — `vault:update-providers` command; startup report from registry
- `tools/tool_registry.py` — register provider tracker
- `config/settings.example.json` — add `cerebras_api_key`, `nvidia_api_key`, `openrouter_api_key`
- `AI/System/Provider-Registry.md` — seed file (written on first run)
- *(de-scoped: bespoke `providers/nvidia_provider.py` — replaced by the generic adapter)*
