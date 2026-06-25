# AI Assistant — User Guide

*A zero-cost AI brain for this Obsidian vault. Last updated: 2026-06-25 (Milestone 10).*

This guide is for **using** the assistant day to day. For the architecture and forward plan, see
[[Project-State]]. For the live list of AI providers, see [[Provider-Registry]].

---

## 1. What it is

A Python service that reads and writes this vault, keeps its memory as Markdown, and routes every
request across **free-tier** AI providers only. It runs in the background (headless) and you talk to
it three ways:

| Interface | Use it for | How |
|---|---|---|
| **Obsidian plugin** (sidebar) | Live chat against the running service | Open the AI Assistant panel; pick a provider from the dropdown, toggle 🔒 Private, and type |
| **Vault watcher** | Async requests from any device | Add frontmatter to a note (see §6) |
| **Terminal** | Debugging / setup / admin commands | `python assistant.py --terminal` |

All three share one **agent loop**: when the AI puts a `vault:` command on its own line, the system
runs it, feeds the result back, and only then writes the final answer. The AI cannot claim it did
something without a real tool result.

---

## 2. Starting and stopping

```bash
# Headless (normal / production) — watcher + HTTP API, no terminal
python assistant.py

# Interactive terminal (debugging, admin commands)
python assistant.py --terminal

# Stop cleanly from anywhere
curl http://127.0.0.1:8765/shutdown
```

On Windows, activate the venv first: `.venv\Scripts\Activate.ps1`. If `pip` ever fails with a
launcher error, use `python -m pip …` (the venv was rebuilt 2026-06-25).

At startup you'll see a **Startup Check** and then the **Provider Registry** table (see §4).

---

## 3. Terminal commands (cheat sheet)

| Command | What it does |
|---|---|
| *(plain text)* | Chat with the assistant |
| `vault:read <path>` | Read a note into context |
| `vault:search <query>` | Full-text search the vault |
| `vault:list [subfolder]` | Browse the folder structure |
| `vault:links <note>` | Read a note plus everything it links to |
| `vault:create <path>` ⏎ `<content>` | Create a note (path on first line) |
| `vault:update <path>` ⏎ `<content>` | Append to a note |
| `vault:research <question>` | Build a prompt to paste into a web AI |
| `vault:summarise <path>` | Summarise a research note |
| `vault:update-providers [provider]` | **Propose** registry updates (see §7) |
| `vault:update-providers apply` | **Commit** a proposed registry update |
| `remember: <fact>` | Save a fact to Learned-Facts.md |
| `/use groq\|google\|cerebras\|webui\|auto` | Pin a provider (or `auto` for smart routing) |
| `private on` / `private off` | Privacy routing on/off (see §5) |
| `allow-webui on` / `allow-webui off` | Permit the web handoff while private |
| `verbose on` / `verbose off` | Show router logs in the console |
| `tools` / `models` / `context` / `status` | Info commands |
| `clear` | Forget the conversation (episode log unaffected) |
| `exit` | Shut down |

> `vault:import` only works interactively (it asks you to paste, then `---end`). The autonomous
> agent cannot use it.

---

## 4. Providers and the registry

The assistant never pays for anything. Every provider it can use is a **row** in
[[Provider-Registry]] (`AI/System/Provider-Registry.md`), served by **one** generic
OpenAI-compatible adapter — so adding a provider is a Markdown edit, not new code.

**Active today:** `google` (Gemini 2.5 Flash), `groq` (Llama 3.3 70B), `groq:llama-3.1-8b-instant`
(high-volume fallback), and `cerebras` (GPT-OSS 120B — needs a `cerebras_api_key`). **Candidates**
(`nvidia`, `openrouter`, `cerebras:zai-glm-4.7`) are listed but **never routed to** until you change
their `status` to `active`. The plugin's provider dropdown lists exactly what's active.

Each row has a `trains_on_data` value (`no` / `yes` / `logs` / `varies`) — this drives privacy
routing (§5). API keys live in `config/settings.json` as `<provider_key>_api_key` and are **never**
stored in the registry.

**How it chooses (when not pinned with `/use`):**
1. **Privacy first** — if the turn is private, drop every provider whose `trains_on_data` isn't `no`.
2. **Health** — skip providers that have failed repeatedly this session (see §8).
3. **Size** — skip providers that can't fit the request.
4. **Task shape** — large/long-form requests prefer high-volume providers (Cerebras); short turns
   prefer the default order: `google → groq → cerebras → groq:llama-3.1-8b-instant`.

Type `models` to see the loaded specs, or `status` to see which providers are built and healthy.

---

## 5. Privacy mode

Some notes shouldn't be sent to a provider that trains on your data. Flag those turns **private** and
the router will only use providers with `trains_on_data = no` (currently **Groq** and **Cerebras** —
**Google is excluded**, because its free tier trains on prompts).

You can set private three ways:

- **Terminal:** `private on` (turn off with `private off`).
- **Plugin:** click the **🔒 Private** toggle next to the provider dropdown (it turns green). The
  dropdown itself is **registry-driven** — it lists exactly the providers the service has loaded from
  `Provider-Registry.md`, so new providers appear automatically. (Under the hood it sends
  `"private": true` to `/chat`.)
- **A note (watcher):** add `private: true` to the note's frontmatter.

**The web handoff and privacy:** a private turn is **never** silently sent to a web AI (which would
expose it). If all privacy-safe providers are unavailable, the assistant stops and asks you to
choose:

- Terminal: it tells you to type `allow-webui on` and resend.
- HTTP: it returns a 503 telling the client to resubmit with `allow_webui_on_private: true`.
- Note: it writes an error asking you to add `allow-webui: true` to the frontmatter.

---

## 6. Using the vault watcher (any device)

Add frontmatter to any note and save it. The watcher (running on the service machine) picks it up,
answers, and writes the result back under `## Assistant Response`.

```yaml
---
assistant-status: pending
assistant-request: Summarise the key points of this note.
private: true        # optional — privacy routing for this note
allow-webui: false   # optional — permit a web handoff while private
---
```

When done, `assistant-status` becomes `done` (or `handoff-pending` / `error`). Obsidian Sync carries
the note to the machine running the watcher, so this works from your phone too.

---

## 7. Keeping the registry fresh (`vault:update-providers`)

Free tiers change constantly. The tracker tool refreshes the registry **safely** — it never
overwrites the live file on its own:

1. **Propose:** `vault:update-providers` fetches the machine-readable source set in
   `provider_source_url` (in `settings.json`), diffs it against the current registry, and writes the
   changes to `AI/System/Provider-Registry-proposed.md`. **`Provider-Registry.md` is untouched.**
   Scope to one provider with `vault:update-providers groq`.
2. **Review** the proposed note in Obsidian — it shows a human-readable diff plus the exact registry
   it would write.
3. **Commit:** `vault:update-providers apply` replaces `Provider-Registry.md` with the proposed
   version, then deletes the proposal. **Restart the assistant** to route on the new registry.

If `provider_source_url` is blank or the source can't be parsed, the tool instead gives you a
`vault:research` prompt to paste into a web AI; save its table and run the flow again.

---

## 8. Health and the 3-provider floor

The router learns provider health from **real traffic only** — it never pings providers to test them
(that would burn daily quotas, especially Google's). If a provider fails several times in a row this
session it's marked **unhealthy** and skipped until a later request succeeds. You'll see a `⚠` flag
in the console, and the **startup report** warns whenever fewer than **3** providers are healthy —
that's your cue to add a `cerebras_api_key` (or promote a candidate) so you always have a safety
margin.

---

## 9. Web handoff (when free tiers run out)

If you pick `/use webui`, or all API providers are exhausted (and the turn isn't private without
opt-in), the assistant packages a clean prompt for any web AI (ChatGPT / Claude / Gemini / DeepSeek).
Paste it in, paste the answer back, and the system even auto-runs any vault searches the web AI
suggests in plain English, then stores the enriched result.

---

## 10. Memory

Everything the assistant remembers is plain Markdown under `AI/Memory/`:

- `User-Profile.md` — who you are; loaded into every session.
- `Facts/Learned-Facts.md` — appended by `remember: <fact>`.
- `Projects/<name>.md` — per-project notes.
- `Episodes/YYYY-MM-DD.md` — a crash-safe log of each session.

Edit any of these in Obsidian; the assistant reads them at startup.

---

## 11. Configuration (`config/settings.json`)

Common keys (see `config/settings.example.json` for the full template):

| Key | Meaning |
|---|---|
| `vault_path` | Absolute path to this vault |
| `default_provider` / `fallback_provider` | Legacy hints; M10 routing is registry-driven |
| `groq_api_key`, `google_api_key`, `cerebras_api_key`, … | Per-provider keys (`<provider_key>_api_key`) |
| `provider_source_url` | Machine-readable source for `vault:update-providers` |
| `max_tokens`, `temperature` | Generation defaults |
| `host`, `port` | HTTP API bind address (default `127.0.0.1:8765`) |

**Never commit real keys.** `config/settings.json` is git-ignored; only
`config/settings.example.json` is tracked.

---

## 12. Troubleshooting

| Symptom | Fix |
|---|---|
| Startup warns "fewer than 3 healthy providers" | Add a `cerebras_api_key`, or promote a candidate to `active` in the registry |
| A private question fails with no answer | All `trains_on_data=no` providers were down; `allow-webui on` (or set `allow-webui: true`) to permit a handoff |
| `models`/`status` don't show Cerebras as ready | Missing `cerebras_api_key`, or its row isn't `active` |
| `vault:update-providers` says "no source configured" | Set `provider_source_url` in `settings.json`, or use the research-prompt fallback it prints |
| Provider keeps getting skipped | It was marked unhealthy after repeated failures; it recovers automatically on the next success |
| `pip` launcher error | Use `python -m pip …` |

To verify the M10 routing behaviour end-to-end, run [[M10-Provider-Routing-Tests]].
