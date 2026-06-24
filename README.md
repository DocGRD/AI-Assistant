# Zero-Cost AI Operating System for Obsidian

A Python service that gives Obsidian an autonomous AI brain — one that reads and writes your
vault, keeps its memory as Markdown, and routes every request across **free-tier** AI providers
only. It runs headless in the background; you interact through the Obsidian sidebar plugin or by
tagging a note for the vault watcher. The terminal exists only for debugging.

> **Status:** Milestones 1–8 complete and tested. Milestone 9 (context-aware plugin + in-place
> editing) and Milestone 10 (provider registry + free-endpoint tracker) are in progress.
> M10 is the current focus.

---

## What it does today

- **Headless by default.** Starts a vault watcher + local HTTP API with no terminal. `--terminal` for interactive debugging.
- **Reads and writes the vault autonomously** through a shared agent loop (`MAX_STEPS = 10`) used by all three entry points (terminal, HTTP server, watcher).
- **Memory as Markdown.** System prompt, web-AI prompt, user profile, learned facts, per-project notes, and crash-safe daily episode logs all live in `AI/` as plain notes.
- **Multi-provider routing across free tiers** (Groq, Google AI Studio), with a Universal Web Handoff that packages a clean prompt for any web AI (ChatGPT / Claude / Gemini) and integrates the response back into the vault.
- **Three separate prompts**, never mixed: system prompt (vault tools), web-AI partner prompt (no vault syntax), and memory context.

## Interfaces

- **Plugin sidebar** (primary): chat live against the background service over HTTP, with a vault-file fallback (Vault mode) that routes through the watcher.
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
- **M10 — Provider registry + free-endpoint tracker.** A live `Provider-Registry.md`, a generic
  OpenAI-compatible provider driven by it, a tracker that proposes updates from a known machine-readable
  source (web-AI handoff as fallback), and task- and privacy-aware routing with a ≥3-healthy-provider floor.
- Later: project awareness, self-testing agent (`vault:shell` whitelist + test runner), local "muscle-memory" scripts.
