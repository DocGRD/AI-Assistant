# Provider Registry

*Last updated: 2026-06-28*
*Active rows verified live against the account keys on 2026-06-28.*
*Update this file by running: `vault:update-providers`*

This file is the single source of truth for every free-tier endpoint the router can use.
The router reads it at startup. Each **active** row becomes a live provider via the generic
OpenAI-compatible adapter — no Python file per provider. To add a provider, add a row.

The Obsidian plugin's **provider dropdown** is also populated from this list (via the service's
`/status` endpoint), so a new **active** row appears there automatically — no plugin edit needed.

## How the columns are used

- `provider_key` — unique key. The API key is read from settings as `<provider_key>_api_key`.
- `base_url` — OpenAI-compatible base URL. The adapter posts to `<base_url>/chat/completions`.
- `model_id` — exact model string passed in the request.
- `context_window` / `tpm` / `rpm` / `rpd` / `tpd` — limits used for routing and trimming.
  Unknown values are marked `?` and treated as "no known limit" by the router.
- `trains_on_data` — `no` | `yes` | `logs` | `varies`. **Notes flagged `private` route only to `no`.**
- `status` — `active` (router uses it) | `candidate` (registered but NOT routed until tested) | `deprecated`.
- `strengths` — task tags the router matches against (e.g. `reasoning`, `long-context`, `fast`, `volume`).

> **Caveat:** Free tiers change without notice and vary by region/account. These figures are
> current best estimates as of the date above. The authoritative numbers are in each provider's
> console. `vault:update-providers` exists precisely because this table goes stale.
>
> **Authoritative model list — `vault:models`:** instead of trusting a curated third-party list, run
> `vault:models` to query each provider's own `/models` endpoint **with your keys** and see exactly
> which models your accounts can use (★ = already in this registry; ⚠ = a registry row no longer
> available to you). That is the source of truth for promoting a `candidate` to `active`.

> **Curated upstream lists** (also stored in settings as `provider_sources`, editable from the plugin
> control panel — maintain them yourself or let the assistant refresh from them):
> - https://github.com/amardeeplakshkar/awesome-free-llm-apis
> - https://github.com/open-free-llm-api/awesome-freellm-apis
> - https://freellm.net/providers/

## Active Providers (verified live — the router builds + routes to these)

| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | trains_on_data | status | strengths | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| google | https://generativelanguage.googleapis.com/v1beta/openai/ | gemini-3.1-flash-lite | 1000000 | 250000 | 15 | 500 | ? | yes | active | fast, high-RPD, long-context | **Primary Google model — ~500 req/day free** (best Google budget). Trains on free prompts → never `private`. Not in EU/UK/CH |
| google | https://generativelanguage.googleapis.com/v1beta/openai/ | gemini-2.5-flash | 1000000 | 250000 | 5 | 20 | ? | yes | active | long-context (1M), multimodal | Only ~20 req/day free — reserved for genuine long-context, not everyday use. Trains → never `private` |
| google | https://generativelanguage.googleapis.com/v1beta/openai/ | gemini-2.5-flash-lite | 1000000 | 250000 | 10 | 20 | ? | yes | candidate | fast, cheap | ~20 req/day free (same cap as 2.5-flash) — superseded by gemini-3.1-flash-lite; kept as a fallback |
| groq | https://api.groq.com/openai/v1 | llama-3.3-70b-versatile | 128000 | 12000 | 30 | 1000 | 100000 | no | active | reasoning, tool-use, fast | Default for `private` turns. Groq does not train on API data |
| groq | https://api.groq.com/openai/v1 | llama-3.1-8b-instant | 131072 | 6000 | 30 | 14400 | 500000 | no | active | high-volume, fast, cheap fallback | most permissive RPD on Groq free tier |
| groq | https://api.groq.com/openai/v1 | meta-llama/llama-4-scout-17b-16e-instruct | 131072 | 30000 | 30 | 1000 | ? | no | active | fast, multimodal, long-context | Llama 4 Scout MoE |
| groq | https://api.groq.com/openai/v1 | openai/gpt-oss-120b | 131072 | 8000 | 30 | 1000 | ? | no | active | reasoning, large | GPT-OSS 120B on Groq |
| groq | https://api.groq.com/openai/v1 | openai/gpt-oss-20b | 131072 | 8000 | 30 | 1000 | ? | no | active | reasoning, small, fast | GPT-OSS 20B on Groq |
| groq | https://api.groq.com/openai/v1 | qwen/qwen3-32b | 131072 | 6000 | 30 | 1000 | ? | no | active | reasoning, multilingual | Qwen3 32B |
| cerebras | https://api.cerebras.ai/v1 | gpt-oss-120b | 65536 | 30000 | 30 | 14400 | 1000000 | no | active | volume, batch, fast, reasoning | Very high TPS; ~1M tokens/day. No training on API data |
| cerebras | https://api.cerebras.ai/v1 | zai-glm-4.7 | 64000 | 30000 | 30 | 14400 | 1000000 | no | active | reasoning, preview | Cerebras GLM-4.7 preview — verified live |
| nvidia | https://integrate.api.nvidia.com/v1 | meta/llama-3.3-70b-instruct | 128000 | 40000 | 40 | ? | ? | logs | active | breadth, quality | NVIDIA NIM. May log prompts → **excluded from `private`** |
| nvidia | https://integrate.api.nvidia.com/v1 | meta/llama-4-maverick-17b-128e-instruct | 128000 | 40000 | 40 | ? | ? | logs | active | multimodal, large MoE | NVIDIA NIM Llama 4 Maverick. **Not for `private`** |

> **Per-model free RPD differs a lot on Google** (from the AI Studio dashboard, not discoverable via
> `/models`): gemini-2.5-flash ≈ 20/day, gemini-2.5-flash-lite ≈ 20/day, **gemini-3.1-flash-lite ≈ 500/day**,
> gemini-embedding ≈ 1000/day. RPD must be maintained by hand here — `vault:models` confirms which model
> ids exist for the account, but not their daily quotas.

## Candidate Providers (registered, NOT routed — flip status to `active` after testing)

| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | trains_on_data | status | strengths | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| nvidia | https://integrate.api.nvidia.com/v1 | meta/llama-3.1-8b-instruct | 128000 | 40000 | 40 | ? | ? | logs | candidate | fast, small | Verified id but timed out on probe — promote once stable |
| openrouter | https://openrouter.ai/api/v1 | meta-llama/llama-3.3-70b-instruct:free | 128000 | ? | 20 | 200 | ? | varies | candidate | breadth, built-in fallback | Needs `openrouter_api_key`. One key → many `:free` models |

## Deprecated / Removed (do not re-add — wrong id or decommissioned)

| provider_key | model_id | removed_date | reason |
|---|---|---|---|
| groq | deepseek-r1-distill-llama-70b | 2026-06-28 | Decommissioned by Groq (model_decommissioned) |
| cerebras | llama-3.3-70b | 2026-06-28 | Not available on this account (404) — only gpt-oss-120b + zai-glm-4.7 |
| cerebras | qwen-3-235b-a22b | 2026-06-28 | Not available on this account (404) |
| nvidia | mistralai/mistral-large | 2026-06-28 | 404 on chat endpoint for this account |
| google | gemini-2.0-flash / gemini-1.5-flash | 2026-06-01 | Retired / superseded by 2.5 Flash + Flash-Lite |

## Routing intent (read by the router)

- **Default (non-private):** `groq / llama-3.3-70b-versatile` (1000/day, no-train, reliable), then
  `cerebras / gpt-oss-120b`. `google / gemini-2.5-flash` is reserved for **long-context** work —
  its free tier is only ~20 requests/day, so it is no longer the everyday default.
- **Default (private notes):** `groq / llama-3.3-70b-versatile`, then `groq / openai/gpt-oss-120b`,
  then `cerebras / gpt-oss-120b` / `cerebras / zai-glm-4.7` — all `trains_on_data = no` (NVIDIA + Google excluded).
- **High volume / batch / large notes:** `cerebras / gpt-oss-120b`, then `groq / llama-3.1-8b-instant`.
- **Speed-critical short turns:** `groq / llama-3.1-8b-instant`, `google / gemini-2.5-flash-lite`.
- **Reasoning-heavy:** `groq / openai/gpt-oss-120b`, `groq / qwen/qwen3-32b`, `cerebras / zai-glm-4.7`.
- **Floor:** keep at least 3 `active` providers healthy at all times. If a provider fails on live
  traffic, the loader flags it in the startup report and the router stops routing to it until it recovers.
