# AI Assistant — Zero-Cost AI Operating System for Obsidian

A Python service that acts as an AI brain for an Obsidian vault. It reads and writes notes, maintains persistent memory as Markdown, routes requests intelligently across multiple free-tier AI providers, and is accessible both as a terminal assistant and through Obsidian directly.

**Hard constraint: zero spend on AI services at any point in the project.**

---

## Current Status — Milestone 5.5 Complete

| Milestone | Status | Description |
|-----------|--------|-------------|
| 1 — Foundation | ✅ | Startup, config, logging, command loop |
| 1.5 — Config System | ✅ | `settings.json` validation, startup diagnostics |
| 2 — AI Provider Layer | ✅ | Groq + Google adapters, router, fallback |
| 3 — Vault Access Layer | ✅ | 4 read tools, tool registry, `vault:` commands |
| 3 patch — Verbose Toggle | ✅ | Clean console by default, `verbose on/off` |
| 4 — Router + Memory | ✅ | Token-aware routing, Markdown memory, context trimming |
| 4 patch — Crash-safe Episodes | ✅ | Open/append/close pattern — crash loses nothing |
| 5 — Research Workflow | ✅ | `vault:research`, `vault:import`, `vault:summarise` |
| 5.5 — Vault Watcher | ✅ | Frontmatter-triggered async requests, chunker |
| 6 — Obsidian Plugin | 🔜 | TypeScript sidebar chat panel + HTTP API |

---

## Quick Start

### Prerequisites

- Python 3.13+
- An [Obsidian](https://obsidian.md) vault
- A free [Groq API key](https://console.groq.com) and/or a free [Google AI Studio key](https://aistudio.google.com/app/apikey)

### Installation

```bash
git clone <repo-url> assistant-core
cd assistant-core
pip install -r requirements.txt
```

### Configuration

Copy or edit `config/settings.json`:

```json
{
  "vault_path": "/path/to/your/obsidian/vault",
  "default_provider": "groq",
  "fallback_provider": "google",
  "groq_api_key": "gsk_...",
  "google_api_key": "AIza...",
  "groq_model": "llama-3.3-70b-versatile",
  "google_model": "gemini-2.5-flash",
  "max_tokens": 2048,
  "temperature": 0.7,
  "log_level": "INFO",
  "watcher_poll_interval": 5
}
```

### Running

```bash
python assistant.py
```

The assistant starts, prints a diagnostic checklist, and opens the chat loop. The vault watcher starts automatically in a background thread.

---

## Features

### Vault Commands

| Command | What it does |
|---------|-------------|
| `vault:read <name or path>` | Read a note and inject it into the AI context |
| `vault:search <query>` | Full-text search all notes |
| `vault:list [subfolder]` | Browse the vault folder tree |
| `vault:links <name>` | Read a note and all its `[[wikilinked]]` notes |
| `vault:create <path>\n<content>` | Write a new note |
| `vault:update <path>\n<content>` | Append content to an existing note |
| `vault:research <question>` | Generate an optimised prompt for external AI |
| `vault:import` | Paste external AI response into vault as a structured research note |
| `vault:summarise <path>` | Load a research note into context; assistant summarises it |

### Memory Commands

| Command | What it does |
|---------|-------------|
| `remember: <fact>` | Save a fact to `AI/Memory/Facts/Learned-Facts.md` |
| `context` | Show current token usage estimate |
| `models` | Show model capabilities and session error log |
| `status` | Show provider health and verbose state |
| `verbose on / off` | Toggle console log output |
| `clear` | Wipe conversation history (episode log unaffected) |
| `exit` | Write session footer, stop watcher, shut down |

### Vault Watcher — Async Requests from Any Device

Any Obsidian note can trigger an AI request by adding frontmatter:

```yaml
---
assistant-status: pending
assistant-request: Summarize this article and extract the key points
---

[Your note content here...]
```

The watcher (running in the background) detects the `pending` status, processes the request using the note's content as context, and writes the response back:

```yaml
---
assistant-status: done
assistant-request: Summarize this article and extract the key points
assistant-responded: 2026-06-07 14:32
---

## Assistant Response

[Generated response here...]
```

This works cross-device via Obsidian Sync — no open ports or phone apps required.

---

## Architecture

```
assistant-core/
│
├── assistant.py              Entry point, chat loop, watcher thread, command dispatcher
│
├── config/
│   ├── config_manager.py     Loads settings.json
│   └── logger.py             File + console handlers, verbose toggle
│
├── providers/
│   ├── base_provider.py      Abstract contract: BaseProvider, Message, exceptions
│   ├── groq_provider.py      Groq SDK adapter
│   ├── google_provider.py    google-genai SDK adapter
│   ├── provider_router.py    Token-aware routing, fallback, error recording
│   └── model_registry.py     Static model specs, session error log, token estimator
│
├── memory/
│   ├── memory_manager.py     Reads/writes AI/Memory/ in vault; crash-safe episodes
│   └── context_manager.py    Trims conversation history to stay within provider limits
│
├── tools/
│   ├── base_tool.py          Abstract contract: BaseTool, ToolResult
│   ├── tool_registry.py      Central dispatcher — only thing assistant.py calls
│   ├── read_note.py          Read one vault note by name or path
│   ├── search_vault.py       Full-text search across all notes
│   ├── list_vault.py         Folder/file tree view
│   ├── get_linked_notes.py   Read a note + all its [[wikilinks]]
│   ├── create_note.py        Write a new note to the vault
│   ├── update_note.py        Append content to an existing note
│   ├── research_prompt.py    Generate optimised prompt for external AI
│   ├── import_research.py    Import pasted research as structured vault note
│   └── summarise_research.py Load research note into context for AI summarisation
│
└── watcher/
    ├── vault_watcher.py      Polling loop — scans for assistant-status: pending
    ├── frontmatter_parser.py Read/write YAML frontmatter without touching note body
    ├── request_handler.py    Process request, call ProviderRouter, write response
    └── content_chunker.py    Split large notes by headings/word-count for chunked processing
```

### Request Flow

```
python assistant.py
    ├── Chat loop (foreground)
    │   ├── vault: command  →  ToolRegistry.run(tool, input)
    │   │                          → injects result into AI context (if read tool)
    │   │                          → memory.append_episode(ep_vault(...))
    │   └── chat message    →  ContextManager.trim(history)
    │                          → ProviderRouter.generate(messages)
    │                              → ModelRegistry.best_provider_for(tokens, order)
    │                              → GroqProvider / GoogleProvider
    │                          → memory.append_episode(ep_chat(...))
    │
    └── Watcher thread (background daemon)
            → polls vault every N seconds
            → finds notes with assistant-status: pending
            → ContentChunker splits if note > 3000 tokens
            → ProviderRouter.generate() per chunk
            → combines chunks, writes ## Assistant Response to note
            → updates frontmatter to assistant-status: done
```

---

## AI Providers

| Provider | Model | Context Window | Free TPM | Free RPM |
|----------|-------|---------------|----------|----------|
| Groq | `llama-3.3-70b-versatile` | 128k tokens | 6,000 | 30 |
| Google AI Studio | `gemini-2.5-flash` | 1,000,000 tokens | 250,000 | 15 |

The router estimates token count before every request and skips providers that cannot handle it, automatically routing large-context requests to Google and fast short requests to Groq.

---

## Vault Memory Layout

The assistant's memory lives entirely inside your Obsidian vault as human-readable Markdown:

```
AI/
├── Memory/
│   ├── User-Profile.md          Loaded at every startup into the system prompt
│   ├── Facts/
│   │   └── Learned-Facts.md     Appended by 'remember: <fact>'
│   ├── Projects/
│   │   └── <project-name>.md    Per-project accumulated knowledge
│   └── Episodes/
│       └── YYYY-MM-DD.md        Session log — written live, crash-safe
├── Research/
│   └── YYYY-MM-DD-<slug>.md     Research notes from vault:import
└── System/
    ├── Project-State.md         Full architecture documentation and forward plan
    └── watcher.service          systemd unit file template for Linux production
```

---

## Production Deployment (Linux)

The watcher can run as a `systemd` service so it listens for requests even when no terminal is open. A unit file template is saved at `AI/System/watcher.service` in the vault.

```
Laptop (dev)   →   git push   →   Linux machine (prod, systemd service)
                                         ↕ Obsidian Sync
                               Obsidian on any device
```

The `vault_path` in `settings.json` is the only setting that differs between machines.

---

## Design Principles

- **Zero cost.** Free-tier providers only. The router enforces this by proactively checking token budgets before every request.
- **Obsidian is the knowledge base.** Memory, research, plans, and session logs all live as Markdown. Nothing important is hidden in databases or binary files.
- **The assistant never imports tools or providers directly.** Adding a capability means one new file + one registry line. Nothing else changes.
- **Crash-safe episode writing.** Session logs are flushed to disk after every event. A hard kill loses nothing already written.
- **Cross-platform from day one.** All paths use `pathlib.Path`.

---

## Extending the System

### Adding a Tool

1. Create `tools/my_new_tool.py` — subclass `BaseTool`, implement `name`, `description`, `run()`
2. Add one import + one line to `_build_tools()` in `tools/tool_registry.py`
3. Optionally add a `vault:mycommand` entry to `VAULT_COMMANDS` in `assistant.py`

See `AI/System/Project-State.md` in the vault for the full interface contract.

### Adding a Provider

1. Create `providers/my_provider.py` — subclass `BaseProvider`, implement `name`, `generate()`
2. Add one entry to `_PROVIDER_CLASSES` in `providers/provider_router.py`
3. Add a `ModelSpec` entry in `providers/model_registry.py`
4. Add the API key field to `settings.json`

---

## Roadmap

- **Milestone 6** — Obsidian Plugin (TypeScript sidebar chat; HTTP bridge to Python service)
- **Milestone 7** — Project Awareness (auto-load relevant project memory from vault context)
- **Milestone 8** — Tool Growth (code analysis, plan generation, task extraction)
- **Milestone 8.5** — Muscle Memory (repeated tasks saved as local Python scripts, zero API calls)
- **Milestone 9** — Advanced Memory (procedural memory, archive, consolidation)
- **Milestone 10** — Context Intelligence (smarter pre-request context selection)
- **Milestone 12** — Multi-AI Orchestration (task-based provider routing, 3+ provider chains)

Full forward plan with file manifests: `AI/System/Project-State.md` in the vault.

---

## Requirements

```
groq
google-genai
python-dotenv
```

Install: `pip install -r requirements.txt`

> **Note:** Do not install `google-generativeai` — it is deprecated. The correct package is `google-genai`.
