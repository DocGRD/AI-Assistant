# AI Assistant — Zero-Cost AI Operating System for Obsidian

A Python service that acts as an AI brain for an Obsidian vault. It reads and writes notes, maintains persistent memory as Markdown, routes requests across multiple free-tier AI providers, exposes a local HTTP API, and is accessible from a sidebar plugin in Obsidian — or from any device via Obsidian Sync.

**Hard constraint: zero spend on AI services at any point in the project.**

---

## Current Status — Milestone 6 Complete

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
| 6 — Obsidian Plugin | ✅ | FastAPI server, TypeScript sidebar, vault-mode fallback |
| **7 — Web Handoff + Provider Override** | 🔜 | Virtual WebUI provider, context packaging, provider switcher |
| 7.5 — Provider Expansion | 🔜 | NVIDIA NIM, expanded Google/Groq model specs |
| 8 — Active Note + Quick-Actions | 🔜 | Plugin context awareness, toolbar shortcuts |
| 9 — Task Harvester | 🔜 | Collect `- [ ]` tasks vault-wide into Todo.md |
| 10 — Project Awareness | 🔜 | Auto-load project memory from note context |

---

## Quick Start

### Prerequisites

- Python 3.13+
- Node.js 18+ (for building the Obsidian plugin — one-time)
- An [Obsidian](https://obsidian.md) vault
- A free [Groq API key](https://console.groq.com) and/or [Google AI Studio key](https://aistudio.google.com/app/apikey)

### Installation

```bash
git clone <repo-url> assistant-core
cd assistant-core
pip install -r requirements.txt
```

### Configuration

Edit `config/settings.json`:

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
  "host": "127.0.0.1",
  "port": 8765,
  "watcher_poll_interval": 5
}
```

### Running

```bash
python assistant.py
```

Three threads start: the terminal chat loop (foreground), the vault watcher (background), and the HTTP API server (background).

---

## Features

### Vault Commands

| Command | What it does |
|---------|-------------|
| `vault:read <name or path>` | Read a note and inject it into AI context |
| `vault:search <query>` | Full-text search all notes |
| `vault:list [subfolder]` | Browse the vault folder tree |
| `vault:links <name>` | Read a note and all its `[[wikilinked]]` notes |
| `vault:create <path>\n<content>` | Write a new note |
| `vault:update <path>\n<content>` | Append content to an existing note |
| `vault:research <question>` | Generate an optimised prompt for external AI |
| `vault:import` | Paste external AI response into vault as structured research note |
| `vault:summarise <path>` | Load a research note into context; assistant summarises it |

### Memory Commands

| Command | What it does |
|---------|-------------|
| `remember: <fact>` | Save a fact to `AI/Memory/Facts/Learned-Facts.md` |
| `context` | Show current token usage estimate |
| `models` | Show model capabilities and session error log |
| `status` | Show provider health, verbose state, HTTP API URL |
| `verbose on / off` | Toggle console log output |
| `clear` | Wipe conversation history (episode log unaffected) |
| `exit` | Write session footer, stop watcher and HTTP server |

### Vault Watcher — Async Requests from Any Device

Add this frontmatter to any Obsidian note:

```yaml
---
assistant-status: pending
assistant-request: Summarize this note and extract action items
---
```

The watcher detects it, processes it using the note content as context, and writes back:

```yaml
---
assistant-status: done
assistant-responded: 2026-06-09 14:32
---

## Assistant Response
[Generated response here]
```

Works across devices via Obsidian Sync — no open ports required.

### Obsidian Plugin

Click the robot icon in the left ribbon to open the chat sidebar.

- **Live mode** (green badge): direct connection to the Python service — instant replies, shared session history
- **Vault mode** (orange badge): service offline or different device — writes a request note to `AI/Chat/`, polls every 3 seconds for the watcher's response. Works from your phone.

---

## Architecture

```
assistant-core/
│
├── assistant.py              Entry point: chat loop, watcher thread, HTTP server thread
├── server.py                 FastAPI: POST /chat, GET /status, GET /history
│
├── config/
│   ├── config_manager.py     Loads settings.json
│   └── logger.py             File + console log handlers, verbose toggle
│
├── providers/
│   ├── base_provider.py      Abstract contract: BaseProvider, Message, exceptions
│   ├── groq_provider.py      Groq SDK adapter
│   ├── google_provider.py    google-genai SDK adapter
│   ├── provider_router.py    Token-aware routing, fallback, error recording
│   └── model_registry.py     Static model specs, session error log, token estimator
│
├── memory/
│   ├── memory_manager.py     Reads/writes AI/Memory/ — crash-safe episodes
│   └── context_manager.py    Trims conversation history to fit provider limits
│
├── tools/
│   ├── base_tool.py          Abstract contract: BaseTool, ToolResult
│   ├── tool_registry.py      Central dispatcher
│   ├── read_note.py          Read one vault note
│   ├── search_vault.py       Full-text search
│   ├── list_vault.py         Folder/file tree
│   ├── get_linked_notes.py   Note + all [[wikilinks]]
│   ├── create_note.py        Write new note
│   ├── update_note.py        Append to existing note
│   ├── research_prompt.py    Generate external AI research prompt
│   ├── import_research.py    Import pasted research as vault note
│   └── summarise_research.py Load research note into AI context
│
├── watcher/
│   ├── vault_watcher.py      Polling loop — scans for assistant-status: pending
│   ├── frontmatter_parser.py Read/write YAML frontmatter
│   ├── request_handler.py    Process request, call router, write response
│   └── content_chunker.py    Split large notes for chunked processing
│
└── obsidian-plugin/
    ├── manifest.json         Plugin identity
    ├── main.ts               Plugin entry: sidebar, ribbon, settings
    ├── ChatView.ts           Chat UI: HTTP mode + vault-file fallback
    └── styles.css            Panel styles (Obsidian CSS variables)
```

---

## AI Providers

| Provider | Model | Context | Free TPM | Free RPD |
|----------|-------|---------|----------|----------|
| Groq | `llama-3.3-70b-versatile` | 128k | 6,000 | 14,400 |
| Google | `gemini-2.5-flash` | 1M | 250,000 | 20 |

The router estimates token count before every request. Requests too large for Groq's 6k TPM limit are automatically routed to Google. Rate-limit hits are recorded and the router avoids that provider for 65 seconds.

Coming in Milestone 7: explicit provider override (`/use groq`, `/use google`), Universal Web Handoff (route any turn through a web AI without losing context), and NVIDIA NIM as a third provider.

---

## Vault Memory Layout

```
AI/
├── Memory/
│   ├── User-Profile.md          Loaded at every startup into the system prompt
│   ├── Facts/Learned-Facts.md   Appended by 'remember: <fact>'
│   ├── Projects/<name>.md       Per-project accumulated knowledge
│   └── Episodes/YYYY-MM-DD.md  Session log — written live, crash-safe
├── Chat/
│   └── chat-<timestamp>.md      Vault-mode plugin messages (watcher processes these)
├── Research/
│   └── YYYY-MM-DD-<slug>.md     Research notes from vault:import
└── System/
    ├── Project-State.md         Full architecture and forward plan
    └── watcher.service          systemd unit file for Linux production
```

---

## Building the Obsidian Plugin

```bash
cd obsidian-plugin
npm install
npm run build          # produces main.js
```

Copy `main.js`, `manifest.json`, `styles.css` to `.obsidian/plugins/ai-assistant/` in your vault. Enable in Obsidian → Settings → Community plugins.

---

## Linux Production (systemd)

A `systemd` unit file template is saved at `AI/System/watcher.service` in your vault. The `vault_path` in `settings.json` is the only setting that differs between your Windows dev machine and the Linux production machine.

---

## Extending the System

### Adding a Tool

1. Create `tools/my_tool.py` — subclass `BaseTool`, implement `name`, `description`, `run()`
2. Add one import + one line to `_build_tools()` in `tools/tool_registry.py`
3. Optionally add a `vault:mycommand` entry to `VAULT_COMMANDS` in `assistant.py`

### Adding a Provider

1. Create `providers/my_provider.py` — subclass `BaseProvider`, implement `name`, `generate()`
2. Add to `_PROVIDER_CLASSES` in `providers/provider_router.py`
3. Add a `ModelSpec` in `providers/model_registry.py`
4. Add the API key to `settings.json`

Full interface contracts: `AI/System/Project-State.md` in your vault.

---

## Requirements

```
groq
google-genai
fastapi
uvicorn[standard]
python-dotenv
```

Install: `pip install -r requirements.txt`

> Do **not** install `google-generativeai` — it is deprecated. The correct package is `google-genai`.
