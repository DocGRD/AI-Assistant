# Zero-Cost AI Operating System for Obsidian

A Python service that gives Obsidian an autonomous AI brain — one that reads and writes your
vault, keeps its memory as Markdown, and routes every request across **free-tier** AI providers
only. It runs headless in the background; you interact through the Obsidian sidebar plugin or by
tagging a note for the vault watcher. The terminal exists only for debugging.

> **Status:** Milestones 1–8 and **10 complete and tested**. Milestone 9 (context-aware plugin +
> in-place editing) is in progress and is the current focus. M10 delivered a registry-driven,
> privacy- and task-aware provider layer with a self-updating registry and health monitoring.

---

## What it does today

- **Headless by default.** Starts a vault watcher + local HTTP API with no terminal. `--terminal` for interactive debugging.
- **Reads and writes the vault autonomously** through a shared agent loop (`MAX_STEPS = 10`) used by all three entry points (terminal, HTTP server, watcher).
- **Memory as Markdown.** System prompt, web-AI prompt, user profile, learned facts, per-project notes, and crash-safe daily episode logs all live in `AI/` as plain notes.
- **Registry-driven multi-provider routing across free tiers** (Groq, Google AI Studio, Cerebras; NVIDIA/OpenRouter registered as candidates). Providers are rows in `AI/System/Provider-Registry.md` served by **one** generic OpenAI-compatible adapter — adding a provider is a Markdown edit, not new code.
- **Privacy- and task-aware selection.** Turns flagged `private` route only to providers that do not train on submitted data (Google is excluded), and never to the web handoff unless you opt in. Large/long-form requests prefer high-volume providers; short turns prefer the default.
- **Health monitoring with a ≥3-provider floor.** Success/failure is tracked from real traffic only (never by probing); a provider that fails repeatedly is flagged and skipped, and the startup report warns when fewer than three providers are healthy.
- **Self-updating registry (propose/commit).** `vault:update-providers` fetches a machine-readable source, writes a proposal to `Provider-Registry-proposed.md`, and only `vault:update-providers apply` commits it — the live registry is never overwritten autonomously.
- **Universal Web Handoff** packages a clean prompt for any web AI (ChatGPT / Claude / Gemini) and integrates the response back into the vault.
- **Three separate prompts**, never mixed: system prompt (vault tools), web-AI partner prompt (no vault syntax), and memory context.

## Interfaces

- **Plugin sidebar** (primary): chat live against the background service over HTTP, with a vault-file fallback (Vault mode) that routes through the watcher. Its **provider dropdown is registry-driven** (populated from the service's `/status`, so new `Provider-Registry.md` rows appear automatically) and it has a **🔒 Private** toggle for privacy routing.
- **Vault watcher** (primary): set `assistant-status: pending` + `assistant-request: <question>` on any note; the watcher processes it and writes back.
- **Terminal** (debug only): `python assistant.py --terminal`.

## Run it

```bash
# Headless (same as production)
python assistant.py

# Interactive terminal (debugging)
python assistant.py --terminal

# Shutdown (from anywhere)
curl http://127.0.0.1:8765/shutdown
# or, under systemd:
sudo systemctl restart ai-assistant
```

Deployment: Windows for development, Linux (systemd) for production. Obsidian Sync keeps the vault
identical on both machines and is what carries note edits made on any device to the Linux box where
the watcher runs.

---

## Architecture (high level)

```
assistant.py        entry point — headless default, threads: watcher + HTTP server
agent_loop.py       shared agent loop (terminal, server, watcher); MAX_STEPS=10
providers/          base_provider, provider_router, model_registry,
                    + generic OpenAI-compatible adapter (M10),
                    + registry_loader (M10), webui_provider (web handoff)
memory/             memory_manager (prompts + episodes), context_manager (trimming)
tools/              read / search / list / links / create / update / research / summarise
                    + replace_note (M9), provider_tracker (M10)
watcher/            vault_watcher, request_handler (uses agent loop), frontmatter_parser
obsidian-plugin/    main.ts, ChatView.ts (HTTP + vault fallback, handoff, M9 context features)
```

Vault system files live under `AI/System/`:

- `Project-State.md` — the canonical project plan and interface contracts.
- `System-Prompt.md` — live system prompt (editable in Obsidian).
- `WebUI-Prompt.md` — web-AI partner prompt (editable in Obsidian).
- `Provider-Registry.md` — live list of free-tier endpoints (M10).

---

## Standing design principles

- **Zero cost.** Free tiers only; the router enforces it.
- **Obsidian is the knowledge base.** Nothing important lives in binary files or databases.
- **Python for the brain, TypeScript for the face.** They talk over HTTP only.
- **Tools produce real results, not claimed ones.** Tool output is injected back into context before the final reply.
- **Privacy is a routing input (M10).** Notes flagged `private` are sent only to providers that do not train on or log prompts.
- **Adding a provider is a Markdown edit (M10).** One generic OpenAI-compatible adapter is driven by rows in `Provider-Registry.md`.

---

## What's next

- **M9 — Context-aware plugin + in-place editing.** Active-note injection, selection context, and a
  *propose/commit* edit model: the agent only ever proposes a change (target region + replacement
  text); the plugin shows it in an interactive dialog where you approve or keep editing. Nothing is
  overwritten autonomously. Sub-note granularity (word / paragraph / whole-note) lives in the plugin,
  which owns the editor offsets; the watcher path stays whole-note.
- ✅ **M10 — Provider registry + free-endpoint tracker (done).** A live `Provider-Registry.md`, one
  generic OpenAI-compatible adapter driven by it, a propose/commit tracker (`vault:update-providers`,
  web-AI handoff as fallback), task- and privacy-aware routing, and per-provider health tracking with a
  ≥3-healthy-provider floor.
- Later: project awareness, self-testing agent (`vault:shell` whitelist + test runner), local "muscle-memory" scripts.
