<!-- help-version: 22 -->
---
tags: [help, user-guide, privacy, settings]
---
# Privacy, Providers & Settings

Part of [[How-To-Use]]. The live provider list is [[Provider-Registry]].

## Privacy — how "private" works
A turn is **private** when you toggle **🔒 Private** in the plugin, a note has `private: true`
frontmatter, or you type `private on` in the terminal. On a private turn:
- Routing uses **only providers that don't train on / log your data** (Google and NVIDIA are excluded).
- The **web is off-limits**: `vault:webresearch` refuses, and the manual web handoff is offered only if
  you explicitly opt in.
- Image **OCR** for a private note uses only no-train multimodal models or local `tesseract`.
- Private notes are kept out of the shared knowledge graph unless `graph_include_private` is on.

Nothing about your vault leaves the machine for indexing, embeddings, OCR (local), or the graph — those
are all local.

## Providers (zero-cost)
Providers are rows in [[Provider-Registry]]; the router picks one per turn by privacy + task, skips
unhealthy ones, and warns below three healthy. Add a provider by adding a row (a Markdown edit).
`vault:models` shows what your keys unlock; `vault:discover-providers` proposes a registry from each
provider's live model list.

**Web-search providers** work the same way — free-first, config-driven. Out of the box it uses keyless
DuckDuckGo (or a self-hosted SearXNG). Add any of `brave_api_key` / `serper_api_key` / `tavily_api_key` /
`exa_api_key` / `google_search_api_key`+`google_cse_id` and it joins the rotation (`web_search_order`).

## The settings panel
Open the sidebar **⚙** gear (or Settings → AI Assistant → *Service settings*). It reads the running
service's `settings.json`, lets you edit every key (secrets are write-only), and **Restart service**.
Some keys apply live (agent steps, tokens, temperature, hybrid weights); the rest need a restart.

### Handy settings
| Setting | Meaning |
|---|---|
| `max_agent_steps` | Tool-steps per turn (default 10) |
| `search_exclude_folders` / `search_include_folders` | Scope `vault:search` (exclude adds to log defaults; include is a whitelist) |
| `graph_include_private` | Show private entities in the graph viewer / guides (default off) |
| `auto_discovery_enabled` / `_hour` / `_interval_days` | Weekly provider-registry refresh |
| `auto_consolidate_enabled` / `_hour` | Nightly memory "dreaming" |
| `auto_graph_enabled` / `graph_build_limit` | Nightly knowledge-graph build (off by default — costly) |
| `episode_archive_days` | Age at which daily episodes are archived (default 30) |
| `web_research_enabled` / `web_max_results` / `web_max_fetches` | Autonomous web research |
| `context_summarization` | Compress long chats into a summary block instead of dropping them |

## What runs automatically (no OS cron)
An in-process scheduler on the box runs **weekly provider discovery** (~3 AM) and **nightly memory
consolidation** (~4 AM, plus the graph build if enabled). All are **propose/commit** — they write
proposals for you to accept, never auto-apply. Run any of them by hand anytime with the one-shot
subcommands (see [[Commands]]).