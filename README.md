# AI Assistant — Zero-Cost AI Operating System for Obsidian

A Python service that acts as an AI brain for an Obsidian vault. It reads and writes notes autonomously, maintains persistent memory as Markdown, routes requests across multiple free-tier AI providers, exposes a local HTTP API, and is accessible from a sidebar plugin in Obsidian — or from any device via Obsidian Sync.

**Hard constraint: zero spend on AI services at any point in the project.**

---

## Current Status — Milestone 8 Complete

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
| 5.5 — Vault Watcher | ✅ | Frontmatter-triggered async requests, content chunker |
| 6 — Obsidian Plugin | ✅ | FastAPI server, TypeScript sidebar, vault-mode fallback |
| 7 — Web Handoff + Provider Override | ✅ | Virtual WebUI provider, context packaging, provider switcher |
| 7.5 — Hardening | ✅ | Agent loop, headless mode, 8 bug fixes, systemd service |
| 8 — Three-Prompt Architecture | ✅ | WebUI-Prompt.md, vault suggestion execution, headless default |
| **9 — Context-Aware Plugin + In-Place Editing** | 🔜 | Active note injection, text selection context, quick-actions, vault:replace |
| **10 — Provider Registry + Free Endpoint Tracker** | 🔜 | Live provider registry in vault, NVIDIA NIM, auto-update workflow |
| 11 — Project Awareness | 🔜 | Auto-load project memory from note context |
| 11.5 — Automated Testing | 🔜 | Self-testing agent, vault:shell whitelist, test runner |
| 12 — Muscle Memory | 🔜 | Repeated tasks become zero-API local scripts |
| 13 — Advanced Memory | 🔜 | Procedural memory, archive, consolidation |

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
# Headless (default) — watcher + HTTP server, no terminal
python assistant.py

# Terminal mode — interactive chat for debugging
python assistant.py --terminal
```

Three threads start: the vault watcher (background), the HTTP API server (background), and either the chat loop (terminal mode) or a clean blocking wait (headless).

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

### Memory Commands (terminal mode)

| Command | What it does |
|---------|-------------|
| `remember: <fact>` | Save a fact to `AI/Memory/Facts/Learned-Facts.md` |
| `context` | Show current token usage estimate |
| `models` | Show model capabilities and session error log |
| `status` | Show provider health, verbose state, HTTP API URL |
| `verbose on / off` | Toggle console log output |
| `clear` | Wipe conversation history (episode log unaffected) |
| `/use groq \| google \| webui \| auto` | Override provider for this session |
| `exit` | Write session footer, stop watcher and HTTP server |

### Three-Prompt Architecture

The system uses three strictly separate prompts — they are never merged:

1. **`AI/System/System-Prompt.md`** — loaded at startup. Contains vault tool instructions and agent loop rules. Used by terminal, plugin, and watcher. Edit in Obsidian to change assistant behaviour.
2. **`AI/System/WebUI-Prompt.md`** — loaded when packaging a web handoff. Contains instructions for the web AI research partner. No vault command syntax — tells the web AI to suggest searches in plain English.
3. **Memory context** (`User-Profile.md` + `Learned-Facts.md`) — appended to prompt 1 at startup.

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

### Universal Web Handoff

When all API providers are exhausted (or you select Web UI mode in the plugin), the system packages your full conversation context into a clean prompt ready to paste into any web AI (ChatGPT, Claude, Gemini, DeepSeek). When you paste the response back, the system automatically detects any vault search suggestions the web AI made and executes them — turning the handoff into a genuine research loop.

### Obsidian Plugin

Click the robot icon in the left ribbon to open the chat sidebar.

- **Live mode** (green badge): direct connection to the Python service — instant replies, shared session history
- **Vault mode** (orange badge): service offline or different device — writes a request note to `AI/Chat/`, polls every 3 seconds for the watcher's response. Works from your phone.
- **Provider toggle**: Auto / Groq / Gemini / Web UI — select per message
- **Web handoff**: copy prompt → paste into any web AI → paste response back → vault searches execute automatically

---

## Architecture

```
assistant-core/
│
├── assistant.py              Entry point: headless default, watcher thread, HTTP thread,
│                             terminal fallback (--terminal)
├── server.py                 FastAPI: POST /chat, GET /status, GET /history,
│                             POST /chat/handoff-return, GET /shutdown
├── agent_loop.py             Shared agent loop (terminal + HTTP + watcher).
│                             MAX_STEPS=10. Self-correcting tool hints.
│
├── config/
│   ├── config_manager.py     Loads settings.json
│   └── logger.py             Daily rotating logs (TimedRotatingFileHandler, 7 days)
│
├── providers/
│   ├── base_provider.py      BaseProvider, Message, exceptions
│   │                         ProviderWebUIHandoff is a sibling to ProviderError, not a subclass
│   ├── groq_provider.py      Groq SDK adapter
│   ├── google_provider.py    google-genai SDK adapter
│   ├── webui_provider.py     Virtual provider — loads WebUI-Prompt.md, raises ProviderWebUIHandoff
│   ├── provider_router.py    Token-aware routing, fallback, tuple[str,str] return
│   └── model_registry.py     ModelSpec, SessionErrorLog, token estimator
│
├── memory/
│   ├── memory_manager.py     System prompt from vault, crash-safe episodes,
│   │                         seeds WebUI-Prompt.md on first run
│   └── context_manager.py    Trims history to fit provider limits
│
├── tools/
│   ├── base_tool.py          BaseTool, ToolResult
│   ├── tool_registry.py      Central dispatcher
│   ├── read_note.py
│   ├── search_vault.py
│   ├── list_vault.py
│   ├── get_linked_notes.py
│   ├── create_note.py        Path normalisation, suspicious-path warning
│   ├── update_note.py        Path normalisation
│   ├── research_prompt.py
│   ├── import_research.py
│   └── summarise_research.py
│
├── watcher/
│   ├── vault_watcher.py      Polling loop, handles pending + handoff-pending
│   ├── request_handler.py    Agent loop for watcher — vault commands execute autonomously
│   ├── frontmatter_parser.py Read/write YAML frontmatter
│   └── content_chunker.py    Split large notes for chunked processing
│
└── obsidian-plugin/
    ├── manifest.json
    ├── main.ts               Plugin entry: sidebar, ribbon, settings
    ├── ChatView.ts           Chat UI: HTTP mode, vault-file fallback, web handoff,
    │                         provider toggle, focus retention, vault_actions display
    └── styles.css
```

---

## AI Providers

| Provider | Model | Context | Free TPM | Free RPD |
|----------|-------|---------|----------|----------|
| Groq | `llama-3.3-70b-versatile` | 128k | 6,000 | 14,400 |
| Google | `gemini-2.5-flash` | 1M | 250,000 | 20 |
| WebUI | user-mediated | ∞ | ∞ | ∞ |

The router estimates token count before every request. Requests too large for Groq's 6k TPM limit are automatically routed to Google. Rate-limit hits are recorded and that provider is avoided for 65 seconds before retry.

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
    ├── System-Prompt.md         Live system prompt — edit in Obsidian to change behaviour
    ├── WebUI-Prompt.md          Web AI partner instructions — edit in Obsidian
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

A `systemd` unit file is at `AI/System/watcher.service` in your vault (and `watcher.service` in the repo root).

```bash
sudo cp watcher.service /etc/systemd/system/ai-assistant.service
# Edit the paths inside the file first
sudo systemctl daemon-reload
sudo systemctl enable --now ai-assistant
sudo systemctl status ai-assistant
```

The service runs headless by default — no `--headless` flag needed. To stop cleanly:

```bash
curl http://127.0.0.1:8765/shutdown
# or
sudo systemctl stop ai-assistant
```

---

## Extending the System

### Adding a Tool

1. Create `tools/my_tool.py` — subclass `BaseTool`, implement `name`, `description`, `run()`
2. Add one import + one line to `_build_tools()` in `tools/tool_registry.py`
3. Optionally add a `vault:mycommand` entry to `VAULT_COMMANDS` in `agent_loop.py` and `assistant.py`

### Adding a Provider

1. Create `providers/my_provider.py` — subclass `BaseProvider`, implement `name`, `generate()`
2. Add to `_PROVIDER_CLASSES` in `providers/provider_router.py`
3. Add a `ModelSpec` in `providers/model_registry.py`
4. Add the API key field to `config/settings.json`

Full interface contracts and the forward plan: `AI/System/Project-State.md` in your vault.

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
