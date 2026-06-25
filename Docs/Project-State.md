# AI Assistant — Project State and Forward Plan

*Last updated: 2026-06-23*
*Project: Zero-Cost AI Operating System for Obsidian*

---

## Context Block for Receiving AI

If you are an AI reading this document to implement a milestone, read this section first.

**What exists:** A working Python assistant service (`assistant-core/`) across nine completed milestones. It starts in headless mode by default (watcher + HTTP server, no terminal required), loads its system prompt from the vault (`AI/System/System-Prompt.md`), talks to Groq and Google AI on free tiers, reads and writes the vault autonomously via an agent loop (MAX_STEPS=10), logs every session event crash-safely to the vault, watches the vault for frontmatter-triggered async requests from any device, exposes a local HTTP API consumed by an Obsidian sidebar plugin, supports a Universal Web Handoff that uses a clean web-AI-specific prompt (`AI/System/WebUI-Prompt.md`), and automatically executes vault search suggestions that web AIs make in plain English.

**Three distinct prompts — never mix them:**
1. `AI/System/System-Prompt.md` — for terminal/plugin/watcher. Contains vault tool instructions. Agent loop executes vault: commands in replies.
2. `AI/System/WebUI-Prompt.md` — for web AI partners. NO vault command syntax. Tells web AI to suggest searches in plain English.
3. Memory context (`AI/Memory/User-Profile.md` + Learned-Facts) — appended to prompt 1 at startup.

**What you need to implement a milestone:** This document plus the existing source files. The Interface Contracts section tells you the exact signatures every new file must follow.

**Conventions:**
- Every new tool is a subclass of `BaseTool` in `tools/`, registered in `_build_tools()` in `tool_registry.py`
- Every new provider is a subclass of `BaseProvider` in `providers/`, registered in `_PROVIDER_CLASSES` in `provider_router.py`
- `assistant.py` never imports tools or providers directly — only `ToolRegistry` and `ProviderRouter`
- All paths use `pathlib.Path`
- Episode logging: call `memory.append_episode(ep_*(...))` after every user-visible event
- `router.generate()` returns `tuple[str, str]` — `(reply, actual_provider_used)`. Always unpack both.
- Agent loop is in `agent_loop.py` — used by terminal, server, AND watcher. One loop, three entry points.
- Headless is the default. Pass `--terminal` for the interactive chat loop.

---

## Project Goal

Build a zero-cost AI brain for Obsidian that works primarily through the vault interface — the plugin sidebar and the watcher frontmatter system. It reads and writes notes autonomously, maintains persistent memory inside the vault as Markdown, routes requests across multiple free AI providers, and when local knowledge runs out, hands off cleanly to any web AI and integrates the response back into the vault. The terminal exists only for debugging and initial setup.

**"Finished" looks like:** You open Obsidian, chat in the sidebar or set `assistant-status: pending` on a note, and the assistant reads relevant context, executes research, writes results back to the vault, and maintains a coherent memory of your projects — all at zero API cost, all readable in Obsidian.

---

## Standing Design Principles

**Zero cost.** All AI providers on free tiers only. The router enforces this.

**Obsidian is the knowledge base.** Memory, research, plans, episode logs, system prompts — all live as Markdown. Nothing important is in binary files or databases.

**Headless by default.** The service runs as a background process. The terminal is for development only. Plugin + watcher are the primary interfaces.

**Three separate prompts.** The system prompt, the web AI partner prompt, and the memory context are kept strictly separate. They are never merged except at the point of use.

**Agent tools produce real results, not claimed results.** The agent loop injects tool results back into context before the final reply. The model cannot claim success without a tool result confirming it.

**The assistant is self-aware of its vault.** It reads Project-State.md when asked about itself, checks Memory/Projects/ before planning, and offers to save decisions after significant conversations.

**Python for the brain, TypeScript for the face.** Service layer is Python. Plugin is TypeScript. They communicate via HTTP only.

**Cross-platform from day one.** All paths use `pathlib.Path`.

**Daily rotating logs.** `TimedRotatingFileHandler`, 7 days. Logs are for crash diagnostics; episodes are for readable session history.

---

## Interface Contracts

### Contract 1 — Adding a New Tool

```python
from tools.base_tool import BaseTool, ToolResult

class MyNewTool(BaseTool):
    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "my_new_tool"   # snake_case, unique

    @property
    def description(self) -> str:
        return "One sentence."

    def run(self, input_data: str) -> ToolResult:
        if not input_data.strip():
            return ToolResult(success=False, output="No input provided.")
        return ToolResult(success=True, output="result", metadata={})
```

Register in `tools/tool_registry.py` → `_build_tools()`.
Add `vault:mycommand` to `VAULT_COMMANDS` in `assistant.py` if user-invokable.
Add to `READ_TOOLS` in `agent_loop.py` if result should go into AI context.

### Contract 2 — Adding a New Provider

```python
from providers.base_provider import BaseProvider, Message, ProviderAuthError, ProviderError, ProviderRateLimitError

class MyProvider(BaseProvider):
    def __init__(self, config: dict):
        super().__init__(config)
        api_key = config.get("my_provider_api_key", "").strip()
        if not api_key:
            raise ProviderAuthError("API key missing.")

    @property
    def name(self) -> str:
        return "myprovider"

    def generate(self, messages: list[Message], system_prompt: str = "",
                 max_tokens: int = 2048, temperature: float = 0.7) -> str:
        ...
```

Register in `_PROVIDER_CLASSES` in `provider_router.py`.
Add `ModelSpec` in `model_registry.py`.
Add API key to `settings.json`.

### Contract 3 — Episode Logging

```python
memory.append_episode(ep_vault(tool_name, detail))
memory.append_episode(ep_chat(user_input, reply, provider=used_provider))
memory.append_episode(ep_remember(fact))
memory.append_episode(ep_error(description))
memory.append_episode(ep_handoff("sent", detail))
memory.append_episode(ep_handoff("returned", detail))
```

### Contract 4 — Agent Loop

```python
from agent_loop import AgentContext, run_agent_loop

ctx = AgentContext(
    user_input=..., history=..., history_lock=..., router=...,
    registry=..., memory=..., ctx_mgr=..., system_prompt=...,
    max_tokens=2048, temperature=0.7, provider_override=None,
    ep_vault_fn=ep_vault, ep_error_fn=ep_error,
    tools_used=[], source_label="plugin",  # or "watcher" or ""
)
reply, used_provider = run_agent_loop(ctx)
```

MAX_STEPS = 10. `ProviderWebUIHandoff` and `ProviderError` propagate to caller.

### Contract 5 — Memory Manager API

```python
memory.load_system_prompt() -> str          # reads AI/System/System-Prompt.md
memory.seed_webui_prompt() -> None          # creates AI/System/WebUI-Prompt.md if missing
memory.load_context(project=None) -> str    # User-Profile + Learned-Facts
memory.open_episode() -> None
memory.append_episode(line: str) -> None
memory.close_episode(error_summary="", tools_used=None) -> None
memory.remember(fact: str) -> str
```

---

## Deployment Architecture

```
Windows laptop (development)
    python assistant.py --terminal   ← explicit terminal mode for debugging
    OR
    python assistant.py              ← headless (default) — same as production

Linux machine (production)
    systemd: python assistant.py     ← headless by default, no flag needed
    unit file: /etc/systemd/system/ai-assistant.service

Obsidian Sync: vault identical on both machines
Plugin: .obsidian/plugins/ai-assistant/ (main.js + manifest.json + styles.css)
```

---

## Current Code Architecture

```
assistant-core/
│
├── assistant.py          Entry point — headless default, agent loop,
│                         watcher+HTTP threads, terminal fallback (--terminal)
├── server.py             FastAPI: POST /chat (active note injection M8),
│                         GET /status, GET /history,
│                         POST /chat/handoff-return (vault suggestion execution),
│                         GET /shutdown
├── agent_loop.py         Shared agent loop — used by terminal, server, watcher.
│                         MAX_STEPS=10. BLOCKED_COMMANDS (vault:import).
│                         Self-correction hints (update→create, read→search).
│
├── START.md              Quick-start guide (venv activation, setup)
│
├── config/
│   ├── config_manager.py Loads settings.json
│   └── logger.py         Daily rotating log (TimedRotatingFileHandler, 7 days)
│
├── providers/
│   ├── base_provider.py  BaseProvider, Message, ProviderError,
│   │                     ProviderWebUIHandoff (sibling, not subclass)
│   ├── groq_provider.py
│   ├── google_provider.py
│   ├── webui_provider.py Loads AI/System/WebUI-Prompt.md from vault.
│   │                     Packages context with clean web-AI instructions.
│   │                     No vault command syntax in packaged prompts.
│   ├── provider_router.py  tuple[str,str] return, provider_override, webui fallback
│   └── model_registry.py   groq + google + webui ModelSpec, SessionErrorLog
│
├── memory/
│   ├── memory_manager.py   load_system_prompt() reads AI/System/System-Prompt.md
│   │                       seed_webui_prompt() creates AI/System/WebUI-Prompt.md
│   │                       load_context() reads User-Profile + Learned-Facts
│   │                       crash-safe episode writing
│   └── context_manager.py  trims history to provider limits
│
├── tools/
│   ├── base_tool.py, tool_registry.py
│   ├── read_note.py, search_vault.py, list_vault.py, get_linked_notes.py
│   ├── create_note.py      path normalisation, suspicious-path warning
│   ├── update_note.py      path normalisation
│   ├── research_prompt.py, import_research.py, summarise_research.py
│   └── [future] detect_project.py, local_script_tool.py, provider_tracker.py
│
├── watcher/
│   ├── vault_watcher.py    polls vault, handles pending+handoff-pending,
│   │                       passes registry to RequestHandler
│   ├── request_handler.py  uses agent_loop — vault commands in watcher
│   │                       responses execute autonomously
│   ├── frontmatter_parser.py
│   └── content_chunker.py
│
└── obsidian-plugin/
    ├── manifest.json, main.ts
    ├── ChatView.ts         HTTP mode, vault fallback, web handoff mode,
    │                       provider toggle, focus retention,
    │                       vault_actions_taken display (M8),
    │                       [M9] active note injection, text selection context,
    │                       [M9] quick-action toolbar, in-place note editing
    └── styles.css
```

**Vault system files:**
```
AI/System/
├── Project-State.md      this file
├── System-Prompt.md      live system prompt — edit in Obsidian
├── WebUI-Prompt.md       web AI partner instructions — edit in Obsidian
└── Provider-Registry.md  live list of free-tier endpoints (M10)
```

---

## Three-Prompt Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  AI/System/System-Prompt.md                                  │
│  + AI/Memory/User-Profile.md + Learned-Facts.md             │
│  → Used by: terminal, plugin (/chat), watcher               │
│  → Contains: vault tool instructions, agent loop rules      │
│  → Agent loop executes vault: commands in model replies      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  AI/System/WebUI-Prompt.md                                   │
│  + AI/Memory/User-Profile.md (as USER CONTEXT section)      │
│  → Used by: WebUIProvider when packaging handoff prompts     │
│  → Contains: instructions for web AI research partner        │
│  → NO vault command syntax — web AI suggests in plain English│
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Handoff return processing (server.py)                       │
│  → Web AI response scanned for plain-English vault suggestions│
│  → "search your vault for X" → vault:search X executed      │
│  → Results appended to response before storing               │
│  → Makes handoff a genuine research loop, not one-shot       │
└─────────────────────────────────────────────────────────────┘
```

---

## Web Handoff Flow

```
User asks question in plugin
    ↓
/use webui selected (or all API providers exhausted)
    ↓
WebUIProvider loads AI/System/WebUI-Prompt.md
    ↓
Packages: WebUI instructions + User context + History + Question
    ↓
User copies prompt → pastes into web AI (ChatGPT/Claude/Gemini/DeepSeek)
    ↓
Web AI responds in plain English
(e.g. "You may want to search your vault for rocket stove dimensions")
    ↓
User pastes response back into plugin
    ↓
POST /chat/handoff-return:
    → Scans response for vault search suggestions
    → Executes them automatically (vault:search rocket stove dimensions)
    → Appends results to response
    → Stores enriched response in history
    → Shows ⚡ auto-executed notice in plugin
    ↓
User can copy the enriched context and send another round to web AI
```

---

## Current Provider Table

| Provider | Model | Context | Free TPM | Free RPD |
|----------|-------|---------|----------|----------|
| Groq | `llama-3.3-70b-versatile` | 128k | 6,000 | 14,400 |
| Google | `gemini-2.5-flash` | 1M | 250,000 | 20 |
| WebUI | user-mediated | ∞ | ∞ | ∞ |

*The full live list of free endpoints is maintained at `AI/System/Provider-Registry.md` (added M10).*

---

## Vault Memory Layout

```
AI/
├── Memory/
│   ├── User-Profile.md          loaded at startup into system prompt
│   ├── Facts/Learned-Facts.md   appended by 'remember: <fact>'
│   ├── Projects/<name>.md       per-project accumulated knowledge
│   └── Episodes/YYYY-MM-DD.md  daily session log — crash-safe
├── Chat/
│   └── chat-<timestamp>.md      vault-mode plugin messages
├── Research/
│   └── YYYY-MM-DD-<slug>.md     research notes from vault:import
├── Scripts/                     (Milestone 12 — local automation)
├── Tests/
│   └── *.md                     test suite files
└── System/
    ├── Project-State.md         this file
    ├── System-Prompt.md         live system prompt (edit in Obsidian)
    ├── WebUI-Prompt.md          web AI partner prompt (edit in Obsidian)
    ├── Provider-Registry.md     live free-endpoint registry (M10)
    └── watcher.service          systemd unit file
```

---

## Runtime Interface

### Primary: Obsidian Plugin (Live mode)
Open the AI Assistant sidebar. Send messages. The service runs headlessly in the background.

### Primary: Vault Watcher
Set `assistant-status: pending` + `assistant-request: <question>` on any note. The watcher processes it and writes the response back.

### Shutdown
The plugin no longer has a dedicated shutdown button (not needed). Use any of these:
```bash
# From any browser or curl:
curl http://127.0.0.1:8765/shutdown
# From systemd:
sudo systemctl restart ai-assistant
```

### Debug only: Terminal
```bash
python assistant.py --terminal
```

---

## Completed Milestones

### M1 — Foundation ✅
### M1.5 — Configuration System ✅
### M2 — AI Provider Layer ✅
### M3 — Vault Access Layer ✅
### M3 patch — Verbose Toggle ✅
### M4 — Intelligent Router + Memory System ✅
### M5 — Research Workflow ✅
### M5.5 — Vault Watcher ✅
### M6 — Obsidian Plugin ✅
### M7 — Universal Web Handoff + Provider Override ✅
### M7.5 — Hardening ✅

Eight bug fixes: agent loop (BUG-001), headless mode (BUG-002), memory context in vault mode (BUG-003), handoff episode logging (BUG-004), plugin input focus (BUG-005), WebUI prompt cleanup (BUG-006), log rotation (BUG-007), venv detection (BUG-008).

### M8 — Three-Prompt Architecture + Headless Default ✅

**Problem solved:** The WebUI packaged prompt was self-contradictory — it told web AIs both to ignore vault commands and to use them. Web AIs (DeepSeek, ChatGPT) responded with `vault:search` commands that the system then ignored. Gemini tried to execute them itself and returned empty results.

**Solution:**
- `AI/System/WebUI-Prompt.md` — new vault file with clean web AI instructions. No vault syntax. Tells web AI to suggest searches in plain English.
- `webui_provider.py` — loads `WebUI-Prompt.md` from vault instead of stripping the system prompt. Falls back to `DEFAULT_WEBUI_PROMPT` if file missing.
- `server.py` — `POST /chat/handoff-return` scans pasted web AI responses for plain-English vault suggestions ("search your vault for X") and executes them automatically. Results appended to response. Plugin shows ⚡ notice.
- Headless is now the **default** mode when no TTY is detected. `--terminal` flag required for interactive chat. `--headless` still works but is redundant.
- `memory_manager.py` — `seed_webui_prompt()` creates `WebUI-Prompt.md` on first run.
- `watcher.service` updated — no `--headless` flag needed in ExecStart.
- Plugin shutdown button removed from sidebar (not needed — `/shutdown` endpoint handles this).

**Testing result:** All M8 functionality confirmed working. No issues.

**Files changed:** `providers/webui_provider.py`, `server.py`, `memory/memory_manager.py`, `assistant.py`, `watcher.service`, `obsidian-plugin/ChatView.ts`

---

## Forward Plan

### Milestone 9 — Context-Aware Plugin + In-Place Note Editing

**Goal:** The plugin becomes fully context-aware and the watcher/agent gains the ability to edit notes in place (not just append a response at the bottom).

#### 9.1 — Active Note Auto-Injection

Before every send, the plugin reads the currently open note and sends it as context. The server already accepts `active_note_path` (M8 stub) — this wires the plugin side.

| Action | File | Detail |
|--------|------|--------|
| MODIFY | `obsidian-plugin/ChatView.ts` | Read `app.workspace.getActiveFile()` before every send; include path in `ChatRequest.active_note_path` |
| MODIFY | `server.py` | `active_note_path` already handled — confirm injection works end to end |

#### 9.2 — Text Selection Context

The user can select text in the Obsidian editor or in the plugin sidebar and add it to the next message as explicit context. This avoids loading an entire note when only a paragraph is relevant.

| Action | File | Detail |
|--------|------|--------|
| ADD | `obsidian-plugin/ChatView.ts` | "Add selection" button (or keyboard shortcut) that reads `app.workspace.activeEditor?.editor.getSelection()` and prepends it to the input as a quoted block |
| ADD | `obsidian-plugin/ChatView.ts` | Visual indicator showing "Selection attached: N chars" when a selection is queued |
| ADD | `obsidian-plugin/styles.css` | Style for the selection-attached badge |

**Selection format injected:**
```
[Selected text from <note-name>]
> <selected content here>

<user's message>
```

#### 9.3 — Quick-Action Toolbar

Buttons in the plugin sidebar that fire pre-formed requests against the active note without typing.

| Button | Action sent |
|--------|-------------|
| Summarise | "Summarise the active note concisely." |
| Find Tasks | "List all action items and tasks in the active note." |
| Fix Grammar | "Fix any grammar and spelling issues in the active note and return the corrected text." |
| Expand | "Expand the key points in the active note with more detail." |

| Action | File | Detail |
|--------|------|--------|
| ADD | `obsidian-plugin/ChatView.ts` | Quick-action bar rendered below provider toggle; each button calls `handleSend()` with the canned message |
| ADD | `obsidian-plugin/styles.css` | `.ai-assistant-quick-bar` styles |

#### 9.4 — In-Place Note Editing (Watcher + Agent)

**Problem:** The watcher currently appends an `## Assistant Response` block at the bottom of a note. For editing tasks (Fix Grammar, restructure, rewrite), appending is wrong — the agent needs to replace the note's body content.

**Solution:** A new `replace_note` tool that overwrites the body of an existing note while preserving its YAML frontmatter. The agent uses this when the request is an edit, not an annotation.

| Action | File | Detail |
|--------|------|--------|
| CREATE | `tools/replace_note.py` | `ReplaceNoteTool` — reads frontmatter, replaces body only, writes back atomically. Input: first line = path, remaining = new body content. Never touches frontmatter. |
| MODIFY | `tools/tool_registry.py` | Register `ReplaceNoteTool` |
| MODIFY | `agent_loop.py` | Add `vault:replace` → `replace_note` to `VAULT_COMMANDS`. Add to `READ_TOOLS`? No — it's a write. Add self-correction hint: if `replace_note` returns "not found", hint to use `vault:create`. |
| MODIFY | `assistant.py` | Add `vault:replace` to `VAULT_COMMANDS` dict and help text |
| MODIFY | `watcher/request_handler.py` | Add `edit_mode` detection: if `assistant-request` contains words like "fix", "edit", "rewrite", "correct", "replace" — set a flag that instructs the agent to use `vault:replace` rather than appending. Pass flag in the user_input preamble. |

**`ReplaceNoteTool` contract:**
```python
# Input: path on first line, new body content on remaining lines
# Behaviour: read file → extract frontmatter → replace body → write back
# Output: ToolResult(success=True, output="✓ Note replaced: <path>")
# Errors: file not found, write failure
```

**Watcher edit mode preamble (injected into user_input):**
```
[Edit mode: this request asks you to rewrite the note content.
Use vault:replace <path> with the revised content.
Do NOT use vault:update (appends only).
Do NOT output the response as a new section at the bottom.]
```

**Vault command syntax:**
```
vault:replace AI/Projects/my-note.md
# My Note Title

Revised content here...
```

#### 9.5 — Plugin In-Place Edit Support

The plugin also benefits from edit mode: when a quick-action like "Fix Grammar" is sent, the response should offer to write the corrected text back to the note.

| Action | File | Detail |
|--------|------|--------|
| MODIFY | `obsidian-plugin/ChatView.ts` | After receiving an assistant reply to an edit quick-action, show a "Write back to note" button that uses `app.vault.modify(file, newContent)` to replace the active note's content |
| MODIFY | `obsidian-plugin/styles.css` | Style the write-back button |

**Security note:** Write-back only applies to the currently open note (the one that was sent as `active_note_path`). The user clicks the button explicitly — the plugin never auto-overwrites.

#### M9 Deliverables Summary

- `tools/replace_note.py` — new tool
- `tools/tool_registry.py` — register
- `agent_loop.py` — vault:replace command
- `assistant.py` — vault:replace in VAULT_COMMANDS
- `watcher/request_handler.py` — edit mode detection
- `obsidian-plugin/ChatView.ts` — active note injection, selection context, quick-action bar, write-back button
- `obsidian-plugin/styles.css` — quick-bar styles, selection badge, write-back button

---

### Milestone 10 — Provider Registry + Free Endpoint Tracker

**Rationale:** The list of free AI endpoints changes constantly — models get added, deprecated, rate limits shift. Hard-coding specs in `model_registry.py` means the router works with stale data. This milestone makes provider knowledge a living vault document that the assistant can update itself.

**Goal:** Maintain `AI/System/Provider-Registry.md` as the single source of truth for all available free-tier providers and models. The router reads from it at startup. The assistant can search for updated specs and write them back using its own tools.

#### 10.1 — Provider Registry Vault File

`AI/System/Provider-Registry.md` — a structured Markdown table the system reads and writes. Format:

```markdown
# Provider Registry

*Last updated: 2026-06-23*
*Update this file by running: vault:update-providers*

## Active Providers

| provider_key | model_id | context_window | tpm_limit | rpm_limit | rpd_limit | status | notes |
|---|---|---|---|---|---|---|---|
| groq | llama-3.3-70b-versatile | 128000 | 6000 | 30 | 14400 | active | free tier |
| groq | llama3-8b-8192 | 8192 | 6000 | 30 | 14400 | active | faster, smaller |
| google | gemini-2.5-flash | 1000000 | 250000 | 15 | 20 | active | best free option |
| google | gemini-2.5-flash-lite | 1000000 | 1000000 | 30 | 1500 | active | fastest google |
| nvidia | llama-3.1-nemotron-ultra-253b-v1 | 128000 | 40000 | 40 | 1000 | candidate | requires testing |

## Deprecated / Removed

| provider_key | model_id | removed_date | reason |
|---|---|---|---|
| groq | mixtral-8x7b-32768 | 2026-03-01 | Deprecated by Groq |
```

#### 10.2 — Registry Parser

New module: `providers/registry_loader.py`

```python
class RegistryLoader:
    """Reads AI/System/Provider-Registry.md and returns list[ModelSpec]."""

    def __init__(self, vault_path: str):
        self._path = Path(vault_path) / "AI/System/Provider-Registry.md"

    def load(self) -> list[ModelSpec]:
        """Parse the Markdown table and return ModelSpec objects."""
        ...

    def seed(self) -> None:
        """Write the default registry if the file does not exist."""
        ...
```

The `ModelRegistry.__init__()` calls `RegistryLoader.load()` at startup and merges results with the hardcoded fallbacks. Registry file entries take precedence over hardcoded specs for any matching `provider_key`.

#### 10.3 — Provider Tracker Tool

New tool: `tools/provider_tracker.py` — `ProviderTrackerTool`

```
vault:update-providers [provider]
```

Behaviour:
1. Reads the current `AI/System/Provider-Registry.md`
2. Generates a `vault:research` prompt targeted at finding current free-tier specs for the named provider (or all providers if blank)
3. Returns the research prompt ready to paste into a web AI — or if called from the agent, triggers `vault:research` automatically
4. After the user pastes back research results (or the agent imports them), a follow-up `vault:update-providers apply` parses the research note and updates the registry table

This keeps the update flow consistent with the existing research workflow: web AI does the current-data lookup, the assistant integrates the result.

#### 10.4 — NVIDIA NIM Provider

Add NVIDIA NIM as a third real API provider. Free tier is available via `api.nvidia.com`.

| Action | File | Detail |
|--------|------|--------|
| CREATE | `providers/nvidia_provider.py` | `NvidiaProvider(BaseProvider)` using `openai` SDK (NVIDIA uses OpenAI-compatible API) |
| MODIFY | `provider_router.py` | Add to `_PROVIDER_CLASSES` |
| MODIFY | `model_registry.py` | Add initial `ModelSpec` for `nvidia` — overrideable by registry file |
| MODIFY | `config/settings.example.json` | Add `nvidia_api_key` field |

**NVIDIA free tier (as of mid-2026):** 40 RPM, 1,000 RPD, 40k TPM for most models. Key model: `nvidia/llama-3.1-nemotron-ultra-253b-v1`.

#### 10.5 — Startup Registry Report

At startup, `run_startup_diagnostics()` prints the provider table from the live registry file, not the hardcoded table. Shows last-updated date, flags any providers that are marked `candidate` (not yet tested).

#### M10 Deliverables Summary

- `providers/registry_loader.py` — new module
- `tools/provider_tracker.py` — new tool
- `providers/nvidia_provider.py` — new provider
- `providers/model_registry.py` — integrate registry loader, add nvidia fallback spec
- `providers/provider_router.py` — register nvidia
- `memory/memory_manager.py` — `seed_provider_registry()` method
- `assistant.py` — `vault:update-providers` command, startup report from registry
- `tools/tool_registry.py` — register provider tracker
- `AI/System/Provider-Registry.md` — seed file (written on first run)

---

### Milestone 11 — Project Awareness

Auto-load relevant project memory when the assistant detects context.

| Action | File | Detail |
|--------|------|--------|
| CREATE | `tools/detect_project.py` | Read frontmatter `project:` tag, match to `AI/Memory/Projects/` |
| MODIFY | `assistant.py` | Reload context when project detected |

---

### Milestone 11.5 — Automated Testing (Self-Testing Agent)

**Goal:** The agent can run its own test suite against the live system.

**What is needed:**

1. **`vault:shell` tool** — controlled subprocess execution with a whitelist of allowed commands:
   ```python
   ALLOWED_COMMANDS = [
       "curl", "python", "systemctl status ai-assistant",
       # scripts in AI/Scripts/ only
   ]
   ```

2. **`vault:test` tool** — reads a test note in structured format, executes each step, checks expected result, writes `result:` back to the note.

3. **Test note format** (machine-readable):
   ```yaml
   ---
   test-id: T8.01
   test-status: pending
   ---
   ## Steps
   1. Send message: "What is 2 + 2?"
   ## Expected
   - reply contains "4"
   - provider_used is "groq" or "google"
   ## Result
   (filled by agent)
   ```

4. **Test runner loop** — agent reads all `AI/Tests/*.md` notes with `test-status: pending`, executes each, marks pass/fail.

**Security constraint:** `vault:shell` only runs commands from the whitelist. The agent cannot execute arbitrary shell commands — only pre-approved test utilities.

**Milestone deliverables:**
- `tools/shell_tool.py` — `VaultShellTool` with whitelist enforcement
- `tools/test_runner.py` — `TestRunnerTool` reads/executes/writes test notes
- Updated test suite notes in machine-readable format
- `vault:test [test-id]` command in `assistant.py`

---

### Milestone 12 — Muscle Memory (Zero-API Scripts)

Repeated tasks become local Python scripts in `AI/Scripts/`. When the agent recognises a repeated pattern, it offers to write a script that runs without any API call.

---

### Milestone 13 — Advanced Memory Architecture

Procedural memory, archive, consolidation. Deferred until vault has thousands of interactions.

---

### Deferred / Long-Term

- **Task Harvester** — scan vault-wide for `- [ ]` tasks into a Todo note. Low priority; can be triggered manually with `vault:search - [ ]` in the meantime.
- **Dreaming and Consolidation** — scheduled review processes.
- **Knowledge Graph Integration** — graph structures for richer retrieval.
- **Multi-Agent Systems** — researcher/planner/coder/reviewer roles. Phase 3.

---

## Explicit Non-Goals

Never train or fine-tune language models. Never store critical information in proprietary databases. Always: Vault → Memory → Retrieval → Context → Existing LLMs.

---

## File Delivery History

| Package | Milestone | Key contents |
|---------|-----------|-------------|
| `milestone7.zip` | 7 | Web handoff, provider override, history lock |
| `milestone7-5.zip` | 7.5 | Agent loop, headless mode, memory passthrough |
| `server-agent-hotfix.zip` | 7.5 | Agent loop in HTTP server |
| `agent-selfcorrect-patch.zip` | 7.5 | Self-correcting tools, agent_loop.py extracted |
| `agent-patch2.zip` | 7.5 | MAX_STEPS=10, vault:import blocked |
| `headless-fixes.zip` | 7.5 | TOCTOU fix, shutdown event, /shutdown endpoint |
| `refactor-agent-prompt.zip` | 7.5/8 | System prompt in vault, agent in watcher |
| `episode-handoff-fix.zip` | 7.5 | ep_chat in handoff-return |
| `milestone8.zip` | 8 | Three-prompt architecture, headless default, WebUI-Prompt.md, vault suggestion execution |

---

*Save this file to `AI/System/Project-State.md` in your vault.*
*The assistant can read it with `vault:read AI/System/Project-State.md`.*
