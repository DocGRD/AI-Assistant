# Provider Registry

*Last updated: 2026-06-24*
*Update this file by running: `vault:update-providers`*

This file is the single source of truth for every free-tier endpoint the router can use.
The router reads it at startup. Each **active** row becomes a live provider via the generic
OpenAI-compatible adapter — no Python file per provider. To add a provider, add a row.

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

## Active Providers

| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | trains_on_data | status | strengths | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| google | https://generativelanguage.googleapis.com/v1beta/openai/ | gemini-2.5-flash | 1000000 | 250000 | 15 | 1500 | ? | yes | active | default, long-context, multimodal | **Trains on free-tier prompts — never receives `private` notes.** Pro removed from free tier (Apr 2026); 2.0 retired (Jun 2026) |
| groq | https://api.groq.com/openai/v1 | llama-3.3-70b-versatile | 128000 | 12000 | 30 | 1000 | 100000 | no | active | reasoning, tool-use, fast | RPD cut from 14400 → ~1000 in 2026; good quality but tight daily cap |
| groq | https://api.groq.com/openai/v1 | llama-3.1-8b-instant | 131072 | 6000 | 30 | 14400 | 500000 | no | active | high-volume, fast, cheap fallback | most permissive RPD on Groq free tier |
| cerebras | https://api.cerebras.ai/v1 | llama-3.3-70b | 128000 | ? | ? | ? | 1000000 | no | active | volume, batch, fastest throughput | ~1M tokens/day, very high TPS; no card, no expiry |

## Candidate Providers (registered, not routed until tested)

| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | trains_on_data | status | strengths | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| nvidia | https://integrate.api.nvidia.com/v1 | nvidia/llama-3.3-70b-instruct | 128000 | 40000 | 40 | ? | ? | logs | candidate | breadth (100+ models) | Verify credit policy in console — old 1000-credit cap may be lifted to pure 40 RPM. Can request 200 RPM |
| openrouter | https://openrouter.ai/api/v1 | meta-llama/llama-3.3-70b-instruct:free | 128000 | ? | 20 | 200 | ? | varies | candidate | breadth, built-in fallback | One key → many `:free` models. RPD rises to 1000 with $10+ balance |

## Deprecated / Removed

| provider_key | model_id | removed_date | reason |
|---|---|---|---|
| groq | mixtral-8x7b-32768 | 2026-03-01 | Deprecated by Groq |
| google | gemini-2.0-flash | 2026-06-01 | Retired by Google |

## Routing intent (read by the router)

- **Default (non-private):** `google / gemini-2.5-flash` — highest daily budget + 1M context.
- **Default (private notes):** `groq / llama-3.3-70b-versatile`, then `cerebras` — both `trains_on_data = no`.
- **High volume / batch / large notes:** `cerebras`, then `groq / llama-3.1-8b-instant`.
- **Speed-critical short turns:** `groq / llama-3.1-8b-instant`.
- **Floor:** keep at least 3 `active` providers healthy at all times. If a provider fails on live
  traffic, the loader flags it in the startup report and the router stops routing to it until it recovers.
