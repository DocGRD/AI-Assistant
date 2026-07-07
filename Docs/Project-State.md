# AI Assistant — Project State and Forward Plan

*Last updated: 2026-07-03*
*Project: Zero-Cost AI Operating System for Obsidian*
*Status: **v1.0.0 — released publicly 2026-07-03** (GitHub pre-release "beta v1.0.0" + BRAT, MIT licensed).
Milestones 1–33 implemented and tested (344 automated tests green), and deployed end-to-end (Linux systemd
service with GPU-accelerated embeddings, driven by the Obsidian plugin over the LAN). Post-release work
(2026-07-07): the plugin was renamed **Loremaster** (id `loremaster` — a meaningful name, verified unused across all 5,456 directory plugins),
and **M30 (anti-hallucination), M31 (chunked edits), M32 (deterministic math), M33 (agent full-command access + autonomous web research)** landed. **Where to resume:** see
[Post-v1.0 — Release Status & Next Work](#post-v10--release-status--next-work)
at the end of this document — it records the one open release chore, the discovery next-step, and the
scoped-but-deferred clean-architecture refactor.*

---

## Context Block for Receiving AI

If you are an AI reading this document to implement a milestone, read this section first.

**What exists:** A working Python assistant service in the `assistant_core/` package (run with `python -m assistant_core`, or the back-compat `python assistant.py` shim). Its modules: `app.py` (bootstrap + terminal loop), `server/` (HTTP API package), `agent_loop.py`, `editing.py`, `scripts_runner.py`, `episodes.py`, `diagnostics.py`, `vault_commands.py`, `paths.py`, plus the `config/`, `providers/`, `memory/`, `tools/`, `watcher/`, and `rag/` subpackages. It starts in headless mode by default (watcher + HTTP server, no terminal required), loads its system prompt from the vault (`AI/System/System-Prompt.md`), and routes across free-tier providers driven by `AI/System/Provider-Registry.md` — Groq, Google AI, Cerebras, and NVIDIA are active (OpenRouter is a registered candidate), all served by one generic OpenAI-compatible adapter. Selection is privacy- and task-aware (M10): `private` turns route only to providers that do not train on data, and a per-provider health tracker skips repeatedly-failing providers while warning below a ≥3-healthy floor. It reads and writes the vault autonomously via an agent loop (MAX_STEPS=10), logs every session event crash-safely to the vault, watches the vault for frontmatter-triggered async requests from any device, exposes a local HTTP API consumed by an Obsidian sidebar plugin, supports a Universal Web Handoff that uses a clean web-AI-specific prompt (`AI/System/WebUI-Prompt.md`), and automatically executes vault search suggestions that web AIs make in plain English. It also **edits notes by propose/commit** (M9 — the agent only proposes; the plugin dialog is the sole commit point), answers from the **whole vault via zero-cost local semantic search** (M11 Vault QA — local embeddings, cited sources, indexing on the GPU box only), offers **context-steering UX** (M12 — `@`-note mentions, a Related-notes panel, folder/tag-scoped Vault QA), provides **quick commands + a vault-stored prompt library** (M13), is **project-aware** (M14 — injects a note's `project:` memory), and can **self-test + run approved local scripts** by propose/commit (M15 — `vault:test`, `vault:run-script`; the agent only proposes, never executes). The HTTP API can be exposed on the LAN with an optional `api_token`.

**Three distinct prompts — never mix them:**
1. `AI/System/System-Prompt.md` — for terminal/plugin/watcher. Contains vault tool instructions. Agent loop executes vault: commands in replies.
2. `AI/System/WebUI-Prompt.md` — for web AI partners. NO vault command syntax. Tells web AI to suggest searches in plain English.
3. Memory context (`AI/Memory/User-Profile.md` + Learned-Facts) — appended to prompt 1 at startup.

**What you need to implement a milestone:** This document plus the existing source files. The Interface Contracts section tells you the exact signatures every new file must follow.

**Conventions:**
- All code lives in the `assistant_core/` package; imports are absolute (`from assistant_core.<sub> import …`). Filesystem locations come from `assistant_core/paths.py`, never ad-hoc `__file__` chains.
- Every new tool is a subclass of `BaseTool` in `assistant_core/tools/`, registered in `_build_tools()` in `tool_registry.py`
- Most new providers need **no Python class** — add a row to `AI/System/Provider-Registry.md`. The router builds one `OpenAICompatibleProvider` per active row. Write a bespoke `BaseProvider` subclass only for a genuinely non-OpenAI-compatible API. (`_PROVIDER_CLASSES` was removed in M10; the legacy groq/google adapters were deleted in the reorg.)
- `assistant_core/app.py` never imports tools or providers directly — only `ToolRegistry` and `ProviderRouter`
- All paths use `pathlib.Path`
- Episode logging: call `memory.append_episode(ep_*(...))` (formatters in `assistant_core/episodes.py`) after every user-visible event
- `router.generate()` returns `tuple[str, str]` — `(reply, actual_provider_used)`. Always unpack both.
- Agent loop is in `assistant_core/agent_loop.py` — used by terminal, server, AND watcher. One loop, three entry points.
- Headless is the default. Pass `--terminal` for the interactive chat loop.

> **Note on file paths in this document:** the *Completed Milestones* and *Forward Plan* sections below name files as they were when that work shipped (e.g. `server.py`, `assistant.py`). Since the reorg those live in the `assistant_core/` package (`server/core.py`, `app.py`, …). The architecture tree above is the current map.

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
from assistant_core.tools.base_tool import BaseTool, ToolResult

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

Register in `assistant_core/tools/tool_registry.py` → `_build_tools()`.
Add `vault:mycommand` to `VAULT_COMMANDS` in `assistant_core/vault_commands.py` if user-invokable.
Add to `READ_TOOLS` in `assistant_core/agent_loop.py` if result should go into AI context.

### Contract 2 — Adding a New Provider

**Most providers are OpenAI-compatible and need no new class (M10).** Add a row to
`AI/System/Provider-Registry.md` (`provider_key | base_url | model_id | context_window | tpm | rpm |
rpd | tpd | trains_on_data | status | strengths | notes`) and put the key in `settings.json` as
`<provider_key>_api_key`. The router builds one `OpenAICompatibleProvider` per **active** row at
startup. Use `status: candidate` to register a provider without routing to it until you promote it.

Write a bespoke `BaseProvider` subclass only for a genuinely non-OpenAI-compatible API:

```python
from assistant_core.providers.base_provider import BaseProvider, Message, ProviderAuthError, ProviderError, ProviderRateLimitError

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
        # map 401→ProviderAuthError, 429→ProviderRateLimitError, else ProviderError
        ...
```

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
from assistant_core.agent_loop import AgentContext, run_agent_loop

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
memory.seed_prompts() -> None               # (M13) seeds AI/Prompts/ examples — never clobbers
memory.seed_scripts() -> None               # (M15) seeds AI/Scripts/ + proposed/ + README
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
    python -m assistant_core --terminal   ← explicit terminal mode for debugging
    OR
    python -m assistant_core              ← headless (default) — same as production
    (python assistant.py [--terminal] still works via the root shim)

Linux machine (production)
    systemd: python -m assistant_core     ← headless by default, no flag needed
    unit file: /etc/systemd/system/assistant.service  (WorkingDirectory = repo root)

Obsidian Sync: vault identical on both machines
Plugin: .obsidian/plugins/ai-assistant/ (main.js + manifest.json + styles.css)
```

---

## Current Code Architecture

```
AI_Assistant/            (repo root — also the systemd WorkingDirectory)
│
├── assistant.py          Thin back-compat shim → assistant_core.app:main
├── logs/                 daily rotating logs (anchored at the repo root)
├── data/                 per-machine RAG index (gitignored, rebuildable)
├── tests/                unittest suite — run from the repo root
├── Docs/                 documentation (mirrored to the vault AI/System + AI/Tests)
│
└── assistant_core/       the service package (run: `python -m assistant_core`)
    │
    ├── __main__.py        `python -m assistant_core` → app.main()
    ├── app.py             Bootstrap + terminal loop — headless default,
    │                      watcher+HTTP threads, terminal fallback (--terminal)
    ├── paths.py           Single source of truth for on-disk locations
    │                      (PACKAGE_DIR, REPO_ROOT, CONFIG_DIR, LOGS_DIR, DATA_DIR)
    ├── episodes.py        Episode line formatters (shared w/ server + watcher)
    ├── diagnostics.py     Startup checks + system-prompt assembly
    ├── vault_commands.py  vault: command table (VAULT_COMMANDS) + dispatcher
    ├── agent_loop.py      Shared agent loop — terminal, server, watcher.
    │                      MAX_STEPS=10. BLOCKED_COMMANDS (vault:import).
    │                      Self-correction hints (update→create, read→search).
    ├── editing.py         M9 shared edit helpers — EDIT prompts, reply cleaning,
    │                      option parsing, EditProposal + AI-EDIT-PROPOSAL block.
    ├── scripts_runner.py  M15 — run_vault_script: runs ONLY an approved
    │                      AI/Scripts/<name>.py (bare name, no traversal, timeout).
    │
    ├── server/            FastAPI HTTP API (package)
    │   ├── core.py         AssistantServer: POST /chat (active-note M8 +
    │   │                   selection/edit M9 → EditProposal; private/allow_webui
    │   │                   M10; vault_qa+sources M11; @-mentions + scope M12;
    │   │                   project: injection M14), GET /relevant, /status,
    │   │                   /history, POST /chat/handoff-return, GET /shutdown;
    │   │                   optional X-API-Key middleware (M11 LAN)
    │   ├── models.py        pydantic request/response schemas + _fastapi_available
    │   └── suggestions.py   plain-English → vault: command parsing
    │
    ├── rag/               M11 Vault QA — embedder (local fastembed), chunker,
    │                      vector_store (numpy → data/vault_index/), indexer
    │                      (incremental), retriever, qa.run_vault_qa, RagService.
    │
    ├── config/
    │   ├── config_manager.py Loads settings.json (lives beside it, gitignored)
    │   └── logger.py         Daily rotating log (TimedRotatingFileHandler, 7 days)
    │
    ├── providers/
    │   ├── base_provider.py  BaseProvider, Message, ProviderError,
    │   │                     ProviderWebUIHandoff (sibling, not subclass)
    │   ├── openai_compatible_provider.py  generic adapter (M10) — one instance per
    │   │                     active registry row; 401→Auth, 429→RateLimit, else Error
    │   ├── registry_loader.py  parses Provider-Registry.md → ModelSpec; skips bad rows
    │   ├── webui_provider.py Loads AI/System/WebUI-Prompt.md; packages clean
    │   │                     web-AI instructions (no vault command syntax).
    │   ├── provider_router.py  per-model build; privacy+task route_order; health
    │   │                     + ≥3 floor; startup_report(); tuple[str,str] return
    │   └── model_registry.py   registry merge over fallbacks; route_order();
    │                           SessionErrorLog (record_success / is_healthy)
    │                     (the bespoke groq/google adapters were deleted in the reorg)
    │
    ├── memory/
    │   ├── memory_manager.py   load_system_prompt(); seed_webui_prompt/prompts/scripts;
    │   │                       load_context(); crash-safe episode writing
    │   └── context_manager.py  trims history to provider limits
    │
    ├── tools/
    │   ├── base_tool.py, tool_registry.py
    │   ├── read_note.py, search_vault.py, list_vault.py, get_linked_notes.py
    │   ├── create_note.py / update_note.py   path normalisation
    │   ├── research_prompt.py, import_research.py, summarise_research.py
    │   └── provider_tracker.py  (M10) vault:update-providers — propose/commit
    │
    └── watcher/
        ├── vault_watcher.py    polls vault; pending + handoff-pending; passes registry
        ├── request_handler.py  uses agent_loop — watcher responses execute autonomously
        ├── frontmatter_parser.py
        └── content_chunker.py

obsidian-plugin/             (TypeScript face — HTTP only, at the repo root)
    ├── manifest.json, main.ts
    ├── ChatView.ts         HTTP mode, vault fallback, web handoff mode,
    │                       [M10] registry-driven provider dropdown (from /status)
    │                       + 🔒 Private toggle + WebUI opt-in on private exhaustion,
    │                       focus retention, vault_actions_taken display (M8),
    │                       [M9] active-note send + "+ Selection" capture,
    │                       [M9] "✎ Edit" toggle / /edit, EditProposal dialog
    │                       (diff + word chips), offset-apply + Vault anchor-commit
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

The router builds one OpenAI-compatible adapter per **active** row of
`AI/System/Provider-Registry.md`. Numbers are mid-2026 free-tier best estimates (they drift — that
is why the registry exists). `trains_on_data = no` rows are the only ones eligible for `private` turns.

| Provider (route key) | Model | Context | Free TPM | Free RPD | trains_on_data | Status |
|---|---|---|---|---|---|---|
| google | `gemini-2.5-flash` | 1M | 250,000 | ~1,500 | yes | active (default, non-private) |
| groq | `llama-3.3-70b-versatile` | 128k | 12,000 | ~1,000 | no | active |
| groq:llama-3.1-8b-instant | `llama-3.1-8b-instant` | 131k | 6,000 | ~14,400 | no | active (high-volume fallback) |
| cerebras | `gpt-oss-120b` | 64k | 30,000 | 2,400 (~1M tok/day) | no | active |
| cerebras:zai-glm-4.7 | `zai-glm-4.7` | 64k | 30,000 | 2,400 | no | candidate (preview) |
| nvidia | `nvidia/llama-3.3-70b-instruct` | 128k | 40,000 | ? | logs | candidate (not routed) |
| openrouter | `…llama-3.3-70b-instruct:free` | 128k | ? | ~200 | varies | candidate (not routed) |
| webui | user-mediated | ∞ | ∞ | ∞ | — | always-available fallback |

*The full live list and routing intent is maintained at `AI/System/Provider-Registry.md` (M10).*

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
├── Prompts/                     (M13) saved prompt library — {{selection}}/{{note}}/{{input}}
├── Scripts/                     (M15) approved local scripts (run by vault:run-script)
│   └── proposed/                agent-proposed scripts await approval (moved up to run)
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
sudo systemctl restart assistant
```

### Debug only: Terminal
```bash
python -m assistant_core --terminal      # or: python assistant.py --terminal
```

### One-shot / maintenance subcommands
```bash
python -m assistant_core --consolidate [--apply]   # M17 dreaming: episodes → durable facts
python -m assistant_core --build-graph [--limit N] # M18 incremental knowledge-graph build
```

### vault: command vocabulary (terminal + plugin chat)
Read/search: `vault:read` · `vault:search` · `vault:query` (structured/exact) · `vault:sources` (provenance audit) · `vault:list` ·
`vault:find` · `vault:links` · `vault:ask`.
Write: `vault:create` · `vault:update` · `vault:copy` · `vault:move` · `vault:trash` · `vault:mkdir`.
Research/knowledge: `vault:research` (manual round-trip) · `vault:webresearch` (autonomous, cited) ·
`vault:summarise`/`vault:summarize` · `vault:ingest` (documents) · `vault:ocr` · `vault:analyze` (an
image) · `vault:graph` · `vault:guide` · `vault:graph-merge`. The plugin's **📎 paperclip** attaches a
vault file → `vault:ingest` (document) or `vault:analyze` (image). Study/Scripture: `vault:passage` (a
Bible passage) · `vault:transcribe` (audio) · `vault:cards` / `vault:review` (flashcards). Providers/index: `vault:models` · `vault:discover-providers` ·
`vault:update-providers [apply]` · `vault:reindex`. Ops: `vault:test` · `vault:run-script`.
(Restructuring + import + discovery + ingest + ocr + graph are user-only — the agent never emits them.)

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

### M10 — Provider Registry + Privacy/Task Routing + Self-Updating Registry + Health Floor ✅

Delivered in two slices. Live data: `AI/System/Provider-Registry.md`.

- **Registry-driven providers via one generic adapter.** `providers/openai_compatible_provider.py`
  (`OpenAICompatibleProvider`) is built per **active** registry row; `providers/registry_loader.py`
  parses `Provider-Registry.md` into `ModelSpec` (bad rows skipped + reported), seeds it on first run,
  and `ModelRegistry` merges the file **over** the hardcoded fallbacks. Adding a provider is a Markdown edit.
- **Per-model routing.** One provider per active row → route keys `google`, `groq`, `cerebras`,
  `groq:llama-3.1-8b-instant`. NVIDIA/OpenRouter stay `candidate` (registered, never routed).
- **Privacy-first, task-aware selection** (`ModelRegistry.route_order`). Privacy is applied **first**:
  `private` turns drop every `trains_on_data != "no"` model (Google excluded) and the WebUI handoff is
  offered only on explicit opt-in. Then health, size, and a task ranking (high-volume → Cerebras; default → Google).
  `private` threads from HTTP `ChatRequest.private`, watcher frontmatter `private: true`, and the terminal `private on` toggle.
- **Health floor.** `SessionErrorLog` tracks consecutive real-traffic failures (no probing); a provider
  is marked unhealthy after 3 and skipped; flags raise on flip and when fewer than 3 distinct provider_keys are healthy.
- **Self-updating registry (propose/commit).** `tools/provider_tracker.py` (`vault:update-providers
  [provider|apply]`) fetches a machine-readable source over plain HTTP, diffs it, and writes
  `Provider-Registry-proposed.md`; `apply` commits it. No source / unparseable → `vault:research` fallback.
  The live registry is never overwritten autonomously.
- **Startup report.** `run_startup_diagnostics()` prints the live registry table (last-updated, active vs
  candidate, health) and warns under the ≥3 floor.

**Tests:** `tests/test_registry_loader.py`, `tests/test_routing.py` (privacy, task shape, candidates-never-chosen, health flip, floor).

---

### M9 — Context-Aware Editing (Propose/Commit) ✅

Shipped after M10, in five reviewable slices. The agent only ever **proposes**; the plugin dialog is
the single commit point — nothing is overwritten autonomously, in any path.

- **One proposal shape** (`editing.py` → `EditProposal`): `scope` (word/paragraph/section/whole-note),
  `intent`, `original_text`, `replacement`/`options`, plus **Live `offsets`** (plugin owns them) or
  **Vault `anchor`** (heading + snippet + occurrence). Rendered through one dialog code path.
- **Context plumbing (Slice 1).** Plugin sends `active_note_path` (finishing M8 9.1) + a captured
  `selection` (text + range + inferred scope); `server.py` injects active-note then selection context.
- **Live edit flow (Slices 2–3).** Explicit trigger (a **"✎ Edit" toggle** *and* an `/edit ` prefix —
  no keyword sniffing). `server._handle_edit` **bypasses the agent loop** (deterministic single-shot
  `router.generate`, no history, no `vault:` execution), forces `private` from the note's frontmatter,
  and returns an `EditProposal`. The dialog shows an original/proposed diff (or **word option chips**);
  **Replace** applies at the offsets after a drift guard (the original must be unchanged); **Keep
  editing** refines. Provider exhaustion → a **WebUI edit opt-in** (paste the web AI's text → proposal).
- **Vault staging (Slice 4).** `assistant-edit: true` (+ `assistant-edit-scope` / `-target`) makes the
  watcher **stage** a proposal — it reads the region (section by heading, or whole-note), generates the
  replacement (privacy threaded), appends an `AI-EDIT-PROPOSAL` block, and sets
  `assistant-status: proposal-pending`. **The body is never written.** The plugin detects the block on
  file-open, renders the *same* dialog, resolves the anchor by exact match, and commits at the file
  level (replace + strip block + status `done`). Anchor miss → "select manually" (fail-safe).
- **Privacy.** Edits honor M10 routing — a `private` note edits only via `trains_on_data = no`
  providers; the WebUI route is offered only on explicit opt-in.

**New/changed:** `editing.py` (new shared module), `server.py` (edit path + `selection`/`scope`/`edit`
+ `proposal`), `providers/provider_router.py` (`allow_webui`), `watcher/request_handler.py` +
`vault_watcher.py` (staging + `proposal-pending`), `obsidian-plugin/ChatView.ts` + `styles.css`.
**Tests:** `tests/test_chat_context.py`, `tests/test_editing.py`.
**De-scoped:** `tools/replace_note.py` (auto-overwrite), the quick-action toolbar, the keyword trigger.

---

### M11 — Vault QA (zero-cost local RAG) ✅

Semantic search + grounded, cited answers over the **whole vault** — the copilot-parity gap. Built in
slices; embeddings run **locally** (free + private), the vector index is a per-machine rebuildable
binary, and **only the always-on GPU box indexes** (the laptop never does).

- **`rag/` package.** `embedder.py` (fastembed `bge-small-en-v1.5`, 384-dim; `embedding_device:
  cpu|cuda`, `embedding_threads`), `chunker.py` (heading-aware), `vector_store.py` (numpy matrix + per-
  note hash, cosine search, persists to `data/vault_index/`), `indexer.py` (incremental by hash;
  excludes AI/System|Episodes|Chat; records per-chunk `private`), `retriever.py` (top-k Hits + cited
  context), `qa.py` (`run_vault_qa`), `service.py` (`RagService` — one shared index; `enabled`
  = `index_on_startup` gates writing).
- **Upkeep.** Startup reindex on the enabled machine; the watcher re-embeds a changed note (hash-
  checked); `vault:reindex [full]` is a manual action allowed anywhere.
- **Ask.** Terminal `vault:ask <q>`; plugin **📚 Vault QA** toggle → `/chat {vault_qa:true}` →
  `HandoffResponse.sources`; answers show clickable **source chips**.
- **Privacy.** If *any* retrieved source is a `private` note, the answer routes only to
  `trains_on_data = no` providers (no web handoff) — private content can't leak via retrieval.
- **LAN.** Optional `api_token` (server `X-API-Key`) so the laptop's plugin can use the box's API
  over the home network (`host: 0.0.0.0` + token; plugin host = box IP + token).

**New/changed:** `rag/*` (new), `server.py` (vault_qa path + sources + api_token), `assistant.py`
(RagService, vault:reindex/ask), `watcher/vault_watcher.py` (incremental index), `obsidian-plugin/*`
(Vault QA toggle, source chips, API token), `requirements.txt` (fastembed, numpy).
**Tests:** `tests/test_rag.py`, `tests/test_chat_context.py` (Vault QA + auth).
**Deployment:** the box sets `index_on_startup: true`, `embedding_device: cuda` (installs
`fastembed-gpu`), `host: 0.0.0.0`, and an `api_token`; the laptop points the plugin at it.

---

### M12 — Context UX (`@`-mentions, Relevant Notes, scoped Vault QA) ✅

Everyday ergonomics on top of M11 — steer what the assistant looks at. All three reuse existing
machinery; privacy/recording carry over.

- **`@`-note mentions.** Plugin: a "+ Note" button and the `@` key open a `FuzzySuggestModal`; picked
  notes become removable `@`-chips sent as `ChatRequest.mentions[]`. Server injects each via `read_note`
  as a `[Mentioned note: …]` block. **Any injected private source (active note or mention) now forces
  no-train routing.**
- **Relevant Notes.** `RagService.relevant_notes(path, k)` averages a note's stored chunk vectors (no
  re-embed) and searches the index excluding itself; `GET /relevant` serves it; the plugin shows a
  "Related" panel under the provider bar (click opens, "+" adds as a mention).
- **Scoped Vault QA.** The indexer records per-chunk `tags` (frontmatter + inline `#tags`) and
  normalises `note_path` to `/`; `vector_store` SCHEMA=2 forces a clean rebuild. `retriever`/`qa` take an
  optional `scope {folder?, tag?}`; `ChatRequest.scope_folder`/`scope_tag` + a plugin scope input
  ("folder/" or "#tag") restrict retrieval.

**New/changed:** `server.py` (mentions injection + private-source forcing, `/relevant`, scope fields),
`rag/{service,indexer,vector_store,retriever,qa}.py`, `obsidian-plugin/*` (note picker, mention chips,
Related panel, scope input). **Tests:** `tests/test_rag.py`, `tests/test_chat_context.py`.

---

### M13 — Quick Commands + Prompt Library ✅

- **Prompt library.** `memory_manager.seed_prompts()` seeds `AI/Prompts/` with example prompts (empty
  folder only; never clobbers). The plugin's **Prompts…** picker (`FuzzySuggestModal` over
  `AI/Prompts/*.md`) substitutes `{{selection}}` / `{{note}}` / `{{input}}` and runs the prompt.
- **Quick actions.** A plugin quick-action bar: *Summarize / Key points / Action items* (chat against
  the active note) and *Fix grammar / Improve* (edit on the selection via the M9 proposal dialog).
  Command-palette: "Summarize active note", "Run a saved prompt".
- **New/changed:** `memory/memory_manager.py`, `assistant.py` (startup seed), `obsidian-plugin/*`.
  **Tests:** `tests/test_memory.py`.

### M14 — Project Awareness ✅

When the active note declares `project: <name>`, `server.py /chat` injects
`AI/Memory/Projects/<name>.md` as a `[Project memory: <name>]` context block (reuses the active-note
injection path + `FrontmatterParser`). Server-only — the plugin already sends `active_note_path`.
**Tests:** `tests/test_chat_context.py`.

### M15 — Self-Testing + Muscle-Memory Scripts (propose/commit) ✅

The agent never executes anything; the user is the commit point.

- **Self-testing.** `vault:test` runs the unittest suite (a fixed command — no input interpolation)
  and reports pass/fail.
- **Muscle-memory scripts.** `scripts_runner.run_vault_script` runs **only** an approved
  `AI/Scripts/<name>.py` — name must be a bare identifier (no path traversal), the file must live
  directly in `AI/Scripts/` (not `proposed/`), and it runs with the venv interpreter, no args, and a
  timeout. The agent can only **propose** a script (write it to `AI/Scripts/proposed/` via
  `vault:create`); you **approve** by moving it up into `AI/Scripts/`, then run `vault:run-script
  <name>`. `memory_manager.seed_scripts()` seeds the folder + a README.
- **New/changed:** `scripts_runner.py`, `assistant.py` (vault:test / vault:run-script),
  `memory/memory_manager.py`. **Tests:** `tests/test_scripts_runner.py`.

---

### M16 — Hybrid (Graph-Aware) Retrieval ✅

Vault QA blends M11 vector similarity with the vault's `[[wikilinks]]` + `#tags` — **zero new cost**;
degrades to exactly the M11 vector ranking when the index has no graph.

- **Graph at index time.** `rag/indexer.py` records per-note outlinks + tags into `store.note_meta`;
  `vector_store.py` persists it at **SCHEMA 3** (one clean rebuild) + `best_chunks_for_notes()` for
  out-of-pool neighbour expansion. **Private notes contribute nothing to the graph.**
- **Hybrid rerank.** `rag/graph.py` (`LinkGraph`) — link resolution, 1-hop (and multi-hop, M16.5)
  neighbours, shared-tag neighbours. `rag/retriever.py` reranks by `vector + β·link + γ·tag`; each
  `Hit` tagged `source=vector|graph`. Tunable via `hybrid_weights` / `hybrid_retrieval` / `hybrid_depth`.
- **Surfaced.** `qa.run_vault_qa` returns `source_kinds`; `vault:ask` marks `(graph)`; the plugin shows
  a dashed **· graph** source chip.
- **Tests:** `tests/test_rag.py` `HybridRetrievalTests`. **Deploy:** one reindex (SCHEMA 3).

### M16.5 — Runtime Config + Plugin Control Panel ✅

Settings are now editable at runtime from the plugin, and key knobs are no longer hardcoded.

- **Configurable agent steps.** `AgentContext.max_steps` (from `max_agent_steps`) replaces the hardcoded
  `MAX_STEPS=10`, threaded at all three call sites (terminal, server, watcher via `ProviderRouter.config`).
- **Hybrid depth.** `rag/graph.py` BFS `neighbors_within(hops)`; retriever `depth` from `hybrid_depth`.
- **Settings/restart API** (`server/core.py`): `GET /settings` (secrets redacted), `PUT /settings`
  (writes `settings.json`; live-applies `max_agent_steps`/`max_tokens`/`temperature`/`hybrid_*`, reports
  `restart_required` for the rest), `POST /restart` (`os.execv`). Admin actions refused when the bind is
  public (`0.0.0.0`) without an `api_token`.
- **Plugin control panel** (`obsidian-plugin/main.ts`): Settings → *Service settings* loads the live
  config, renders every key (toggles / numbers / nested `hybrid_weights` / write-only secrets, tagged
  live vs restart), saves changed keys, and offers **Restart service**.
- **Tests:** `tests/test_agent_loop.py`, `tests/test_rag.py` (depth), `tests/test_chat_context.py`
  `SettingsApiTests`.

### M16.6 — Vault File Operations ✅
`vault:find` (recursive glob), `vault:copy` / `vault:move` / `vault:trash` (recoverable) / `vault:mkdir`,
all path-jailed (`paths.resolve_in_vault`); restructuring ops are non-autonomous. Default `max_tokens`→4096.
*Full detail under Forward Plan → M16.6.*

### M16.7 — Self-Discovering Provider Registry ✅
`vault:discover-providers` builds a proposed registry from each provider's live `/models` (chat models
capability-tagged; non-chat kept in a second table); weekly auto-run via the scheduler. Propose/commit.

### M17 — Dreaming & Consolidation ✅
Nightly pass: episodes → durable-fact proposals (forced-private, deduped), episode archival into digests,
and live context summarization. `--consolidate [--apply]`, plugin Memory-review panel, in-process scheduler.

### M18 — Semantic Knowledge Graph + Guides ✅
`vault:graph <note>` / `--build-graph` extract entities/relations → linked Markdown under `AI/Graph/`;
plugin Graph viewer + entity browser; `vault:guide <topic>` cited overview; `vault:graph-merge` alias dedup.

### M19 — Image, Handwriting & Excalidraw ✅
`vault:ocr <note>` (free multimodal + tesseract fallback → `AI/Derived/` sidecar); Excalidraw text indexed.
Privacy-forced. Searchable in Vault QA.

### M20 — Agent Planner Robustness ✅
Deliverable tools end the turn; externalized `TaskLedger` (→ `AI/System/Task-State.md`) for cross-provider
continuity; research paste-back saves verbatim + non-agentic summary + real related notes + short title.

### M21 — Web-Capable Research ✅
`vault:webresearch <question>` — config-driven multi-provider web search (keyless DuckDuckGo / SearXNG;
Brave / Serper / Tavily / Exa / Google CSE when keyed) → fetch → cited synthesis saved to `AI/Research/`.
Privacy hard-blocked. `vault:search` gained plugin-configurable folder scope.

### M22 — Document Ingestion ✅
`vault:ingest <file>` — extract PDF/EPUB/DOCX/txt (optional libs, graceful) → `AI/Library/<slug>.md` with
per-page provenance anchors, indexed for Vault QA; optional graph feed. *Detail under Forward Plan → M22.*

---
## Forward Plan

### Milestone 16 — Hybrid (Graph-Aware) Retrieval ✅ (completed — see Completed Milestones; M16.5 added runtime config + control panel)

**Goal:** improve Vault QA recall/precision by blending M11 vector similarity with the structure the
vault *already* has — `[[wikilinks]]` and `#tags`. **Zero new cost** (deterministic, no LLM). This is
the cheap, high-leverage substrate M18 later builds on.

**Grounding (current code):** `rag/retriever.py` (`Retriever.retrieve(query, k, scope)` → `Hit`s),
`rag/vector_store.py` (`search(qvec, k, predicate)`), `rag/indexer.py` (already records `note_path`,
`heading`, `tags`, `folder`, `private` per chunk; SCHEMA=2), `rag/service.py` (`relevant_notes`, M12),
`tools/get_linked_notes.py` (resolves `[[links]]`). The link graph is free — every note is already read
at index time.

**Slices (independently shippable):**
1. **Capture the link/tag graph at index time.** Extend `indexer.py` to record per-note **outlinks**
   (resolved `[[links]]`) alongside the existing `tags`; persist a small adjacency map in
   `data/vault_index/` (rebuildable, gitignored — same status as the vector store). Bump the index
   SCHEMA → one clean rebuild (as M12 did).
2. **Hybrid scorer in the retriever.** After the top-N vector hits, expand the candidate set with
   **1-hop link neighbours** and **same-tag notes**, then rerank by
   `score = α·vector + β·link_proximity + γ·tag_overlap` (weights in `settings.json`, sensible
   defaults; neighbour count capped to bound context). `qa.run_vault_qa` passes through unchanged.
3. **Surface in UX.** Vault QA source chips label whether a source came from **vector** or **graph**;
   the M12 Related panel can reuse the graph signal. Scope (folder/tag) and the privacy rule are
   unchanged — a public note linking a private note must **not** pull private content into a
   non-private answer (the existing private-source forcing covers this).
4. **Tests + docs.** `tests/test_rag.py`: a tiny linked-note fixture where a linked neighbour is
   retrieved that vector-only would miss; tag-overlap boost; weight plumbing. Project-State M16 entry +
   `AI/Tests/M16-Hybrid-Retrieval-Tests.md`; mirror vault↔Docs.

**Risks:** context bloat from over-expansion (cap neighbours); weight tuning (start conservative);
privacy via links (enforced by the existing no-train-on-private-source rule); one forced reindex.

---

### Milestone 16.6 — Vault File Operations ✅ (implemented)

**Goal:** give the agent the tools to *discover deeply* and *restructure* the vault in one step, instead
of nudging it folder-by-folder or replaying hundreds of read+create calls. Surfaced by T3.21 (the agent
had to be told to "look deeper" and couldn't copy a folder tree).

**Shipped (commits on `dev`):** Slice 1 `vault:find <glob>` (`tools/find_notes.py`, recursive, no
200-cap, in `READ_TOOLS` — autonomous-safe). Slices 2-3 `tools/file_ops.py`: `vault:copy <src> -> <dst>`
(note or `copytree` folder), `vault:move`, `vault:trash` (→ `.trash/`, timestamp on collision, never
hard-deletes), `vault:mkdir`. Slice 4 path-jail centralised in `paths.resolve_in_vault()` (rejects `..`,
absolute, symlink breakout) — used by every write op. All four restructuring ops are in
`agent_loop.BLOCKED_COMMANDS` (execute only on explicit user invocation; the agent gets a "describe it,
let the user run it" message) and flagged user-only in the System-Prompt (×3). Slice 5 default
`max_tokens` 2048→4096 (adapter fallback; live config already 4096). Tests:
`tests/test_vault_fileops.py` (copytree, move, trash recoverable + collision, mkdir parents, jail rejects
escape) + `tests/test_find_notes.py`; both in `vault:test`. Full suite 138 green.

**Deferred:** `vault:tree <folder> [depth]` (slice 1's second tool — `vault:find` covers the deep-listing
need); a plugin confirm-dialog for copy/move/trash (terminal explicit-invocation is the interim).

**Grounding (current code):** `tools/` (`BaseTool` subclasses registered in `tool_registry._build_tools`),
the `vault:` table in `vault_commands.py` + `agent_loop.VAULT_COMMANDS`, `READ_TOOLS` (results injected
into context), and `BLOCKED_COMMANDS` (commands that may not run autonomously, e.g. `vault:import`).
Reuses the M9 propose/commit discipline for anything destructive.

**Slices:**
1. **Discovery (read-only, autonomous-safe).** `vault:find <glob>` (e.g. `06 - Projects/**/*.md`) —
   `rglob`, paginated, **no 200-note cap**; `vault:tree <folder> [depth]` — recursive tree with
   per-folder counts. Both join the agent loop like `vault:search` (added to `READ_TOOLS`). Fixes the
   "look deeper" / truncated-listing friction.
2. **Copy (restructure).** `vault:copy <src> <dst>` — copies a note **or a whole folder tree**
   (`shutil.copytree`), the "061 - Projects" use case in one op. Lower risk (originals untouched), but
   still **propose/commit**: the tool returns the *plan* ("copy N notes → …") and the user confirms.
3. **Move / trash / mkdir.** `vault:move <src> <dst>` (rename/move), `vault:trash <path>` (→ Obsidian
   `.trash/`, recoverable — never hard-delete), `vault:mkdir <path>`. These are **destructive →
   `BLOCKED_COMMANDS`** for autonomous runs; they execute only via an explicit confirm step / plugin
   dialog.
4. **Safety (all write ops).** Every path is resolved and **jailed inside the vault root** (reject `..`,
   absolute escapes, symlink breakout). Reuses the create_note suspicious-path guard.
5. **Tokens.** Bump the default `max_tokens` 2048 → **4096** (the T3.21 reply truncation); the context
   manager already reserves `max_tokens` against the window, so 4096 is safe on every active provider
   (≥64k windows). Tunable live via the M16.5 control panel.
6. **Tests + docs.** `tests/test_vault_fileops.py` (glob enumeration, copytree plan, path-jail rejects
   `..`/absolute, trash→.trash). Project-State M16.6 + `AI/Tests/M16-6-FileOps-Tests.md`; mirror.

**Risks:** destructive bulk ops (mitigated by propose/commit + `.trash` + path-jail + non-autonomous);
large copies (report size, confirm first); glob breadth (paginate). **Zero added API cost** — all local.

---

### Milestone 16.7 — Self-Discovering Provider Registry ✅ (core implemented; probe/cache deferred)

**Goal:** make **your own accounts** the source of truth for the registry instead of curated
third-party lists. `vault:discover-providers` queries every configured provider's `/models`,
keeps only models that **actually work on the free tier**, **classifies each by what it's good at**, and
writes a `Provider-Registry-proposed.md` (propose/commit). The curated `provider_sources` become a
documented fallback only.

**Shipped (commit on `dev`):** `assistant_core/providers/registry_proposer.py` —
`is_chat_model()` (heuristic prefilter: drops `*embed*`/`whisper*`/`*-tts*`/`*guard*`/`*rerank*`/
image/audio/live), `classify_strengths()` (id→`reasoning`/`fast`/`small`/`multimodal`/`code`/`quality`/
`long-context`), `build_proposed_registry()` (full proposed table; **preserves existing active status,
RPD, and hand-edited notes**; new models → `candidate`). Non-chat models (embedding / transcription /
TTS / safety / rerank / image) are **not dropped** — `classify_non_chat()` sorts them into a second
"Specialized / non-chat" table kept for future use; its header omits `status`, so `RegistryLoader`
ignores it for routing while the entries stay on file. Wired as the `vault:discover-providers` terminal
command in `app.py` (loads existing specs via `RegistryLoader`, calls `discover_models()`, writes
`AI/System/Provider-Registry-proposed.md` between the tracker's BEGIN/END markers so the existing
`vault:update-providers apply` commits it). Tests: `tests/test_registry_proposer.py` (filter, classify,
preserve-notes, candidate-marking, error-provider skip) + added to `vault:test`.

**Weekly auto-run:** `assistant_core/scheduler.py` `DiscoveryScheduler` — an in-process daemon thread
(no OS cron / Task Scheduler; cross-platform, lives with the service) ticks every ~30 min and once a week
in a night-time hour runs `discovery_job.run_discovery_proposal()` (shared with the terminal command),
writing the proposal for review — it never auto-commits. Config-gated (`auto_discovery_enabled`,
`auto_discovery_interval_days` = 7, `auto_discovery_hour` = 3) and stateful (`data/discovery_state.json`
records the last run so a restart doesn't re-fire). `discovery_due()` is a pure, unit-tested decision.

**Deferred:** Slice 1b **confirm-probe** (1-token chat call per survivor to separate free-tier from
paid/quota) and the **(provider,model,day) cache** — the heuristic prefilter + `candidate`-by-default is
the conservative interim (a model only goes `active` after a human review or `vault:models` confirms it).
Slice 2's editable `AI/System/Model-Capabilities.md` override map and Slice 4's `provider_sources`
demotion also remain to do.

**Grounding:** `providers/model_discovery.py` (M16.x — `discover_models` already lists `/models` per
provider with an injectable `list_fn`), `tools/provider_tracker.py` (the M10 propose/commit tracker that
writes `Provider-Registry-proposed.md`), `OpenAICompatibleProvider` (for the confirm-probe), and the
registry's `strengths` column (already consumed by task-aware routing).

**Slices:**
1. **Free-tier + chat filter.** A `/models` list includes paid, non-chat, and preview entries (NVIDIA
   returns 121, Google 56). Two-stage: (a) **heuristic prefilter** drops obvious non-chat by id
   (`*-embed*`, `whisper*`, `*-tts*`, `*guard*`, `*rerank*`, image-gen, vision-*embed*); (b) **confirm
   probe** — a 1-token chat call per survivor (reusing the exact check that verified the active rows):
   `200` → usable; `402/403/quota` → paid/not-free; `404` → not chat. Results **cached by (provider,
   model, day)** so a daily refresh re-probes only new/changed models — keeps it within free RPD.
2. **Capability classification ("good at / for").** Tag each kept model with `strengths`
   (`reasoning` / `fast` / `small` / `long-context` / `multimodal` / `code` / `volume` / `tool-use`)
   from: id heuristics (`gpt-oss`/`qwen3`/`deepseek-r1`→reasoning; `8b`/`mini`/`lite`/`instant`→fast,small;
   `scout`/`maverick`/`vision`/`*-vl`→multimodal; `coder`/`codestral`/`codegemma`→code; size→quality)
   plus an **editable `AI/System/Model-Capabilities.md` family→tags map** (you maintain overrides), with
   an optional budgeted LLM pass for unknowns. `context_window` taken from `/models` metadata when present.
3. **Propose the registry.** Build `Provider-Registry-proposed.md` **grouped/sorted by strength**, with a
   suggested `status` (`active` for free-confirmed chat models, else `candidate`), **preserving your
   hand-edited notes/overrides** on existing rows (merge, don't clobber). `vault:update-providers
   discover` writes it; `vault:update-providers apply` commits. Never autonomous.
4. **Demote curated lists.** `provider_sources` documented as a fallback/cross-check only; discovery is
   the primary path.
5. **Tests + docs.** Fake `list_fn` + fake probe + classifier fixtures: non-chat filtered out, a
   paid/quota model excluded, strengths assigned, proposal preserves existing notes. Project-State entry
   + `AI/Tests/`; mirror.

**Risks:** probe cost (cached + heuristic prefilter + only on demand/daily); misclassification (editable
override map + candidate-by-default); providers that don't expose limits in `/models` (fall back to `?`).

---

### Milestone 17 — Dreaming & Consolidation (scheduled) ✅ (all 5 slices implemented)

**Goal:** a **daily** offline pass on the always-on box that turns *episodic* memory into *durable*
memory, archives old episodes, and keeps the index fresh — **propose/commit**, **privacy-forced**, and
**budget-aware**. Subsumes the old "Advanced Memory Architecture" item, and adds **live context
summarization** (summary-based compression for long sessions).

**Shipped (commits on `dev`):** `assistant_core/consolidation.py` `ConsolidationEngine` (Slice 1) —
reads episode notes newer than a **watermark** (`AI/Memory/.consolidation-state.json`; the in-progress
current day is skipped so it's never half-consolidated), asks the LLM with a conservative prompt under
**forced-private routing** (no-train providers only, no web handoff) for ≤6 durable facts per day,
**dedupes** them against `Learned-Facts` with the local embedder (cosine ≥ 0.86) plus exact-text match,
and writes a review note to `AI/Memory/proposed/consolidation-YYYY-MM-DD.md`. **Live memory is never
edited** unless accepted. Slice 3 — one-shot `python -m assistant_core --consolidate [--apply]` (idempotent
via the watermark) and a nightly run folded into the M16.7 scheduler, now `scheduler.MaintenanceScheduler`
(weekly discovery + nightly consolidation in one daemon; `consolidate_due()` is a pure, unit-tested
once-per-night decision; embedder resolved lazily at ~4 AM so startup isn't slowed). Config:
`auto_consolidate_enabled` / `auto_consolidate_hour` (4). `AI/Memory/proposed` added to the RAG excludes.
Tests: `tests/test_consolidation.py` (parse/dedupe/forced-private/watermark/skip-today/apply) +
`consolidate_due`. Suite 170 green.

**Slice 2 (archival):** `archive_old_episodes()` moves raw daily episodes older than `episode_archive_days`
(30) into `AI/Memory/Episodes/Archive/` and indexes each in a monthly digest (`digest-YYYY-MM.md`);
mechanical, additive, reversible; folded into the nightly pass via `run(archive_days=…)`.

**Slice 4 (plugin Memory-review):** `list_proposals()` / `apply_proposal()` + server `GET /memory/proposals`
and `POST /memory/proposals/apply` (path-jailed). The plugin shows a "🧠 Memory review" panel of proposed
facts as accept/reject checkboxes; **Save selected** merges the ticked facts into `Learned-Facts` and
resolves (deletes) the proposal, **Dismiss** drops it. Reuses the propose/commit pattern.

**Slice 5 (live context summarization):** `context_manager.py` Pass 3 now condenses the oldest chat span
into one `[Summary of earlier conversation: …]` block via a single LLM call instead of stubbing turns —
opt-in (`context_summarization`, default off), privacy carried through (`trim(..., private=…)`), and falls
back to the lossy trim if the call fails. Wired through the agent loop, server, and terminal.

Tests: archival (move/keep/digest/no-reprocess), proposal list/apply/path-jail, and summarization
(summary replaces stubs + privacy + failure fallback + disabled-no-call). Full suite 179 green; plugin
`tsc` clean + built + deployed.

**Grounding:** `memory/memory_manager.py` (episodes under `AI/Memory/Episodes/`, `Learned-Facts.md`,
`Projects/<name>.md`, crash-safe writes, `seed_*`), the M10 privacy routing (`private=True` →
no-train providers), the high-volume providers (Cerebras / Groq-8b) for token-heavy work,
`rag/service.py` `reindex()`, and the M15 one-shot subcommand precedent (`app.py` argv dispatch).

**Slices:**
1. **Consolidation engine (read-only → proposal).** New `assistant_core/consolidation.py`: read
   episodes since a **watermark** (state in a small `AI/Memory/.consolidation-state` note); summarize
   per day; extract candidate durable facts via the LLM with a strict, conservative prompt (forced
   **private** routing, chunked + budgeted); **dedupe** candidates against existing `Learned-Facts`
   using the M11 embedder; flag contradictions. Write everything to
   `AI/Memory/proposed/consolidation-YYYY-MM-DD.md`. **Live memory is never edited.**
2. **Archival + digests (mechanical, auto).** Roll raw daily episodes older than *N* days into
   weekly/monthly digest notes and move the raw files to `AI/Memory/Episodes/Archive/`. Because this is
   additive + reversible (and logged), it runs automatically in the nightly pass — the *content*
   changes in Slice 1 stay propose/commit, but archiving "just happens" (this is the "daily dreaming
   for archiving" you asked for). Then `rag_service.reindex()` so the index reflects the moves.
3. **Cron + one-shot mode.** `python -m assistant_core --consolidate [--apply]` (idempotent via the
   watermark; aborts cleanly if the day's RPD budget is low). Ship a sample crontab line + an
   `AI/Scripts/` helper (ties into M15). Logs an episode (`ep_*`).
4. **Plugin review affordance.** When `AI/Memory/proposed/consolidation-*.md` exists, the plugin shows
   a "Memory review" panel rendering proposed facts as accept/reject — reusing the M9 propose/commit
   dialog pattern. Apply merges into `Learned-Facts` / `Projects`.
5. **Live context summarization (folded in).** Replace the lossy trimming in
   `memory/context_manager.py` with **summary-based compression**: instead of dropping the oldest
   chat turns / vault blocks outright (passes 2–3 today), an LLM condenses the about-to-be-trimmed span
   into a short `[Summary of earlier conversation: …]` block that stays in history. Reuses this
   milestone's summarization machinery + budget guard; privacy carries over (a private turn summarizes
   only via no-train providers). Gated by a setting (`context_summarization: true`); falls back to the
   current trim if the summarizer call fails, so a long session degrades gracefully instead of losing
   old context wholesale. This is the everyday-facing half of M17 (the nightly pass is the other half).
6. **Tests + docs.** Deterministic tests with a fake router/embedder: episodes→proposal; a near-dup is
   suppressed; a contradiction is flagged; archival moves files + writes a digest; the watermark
   prevents re-processing; **context summarization replaces a trimmed span with a summary block and
   falls back to trim on failure**. Project-State M17 + `AI/Tests/M17-Dreaming-Tests.md`; cron setup
   added to the Deployment Guide; mirror.

**Risks:** hallucinated facts (propose/commit + contradiction flags + conservative prompt); cost/RPD
(off-peak, high-volume provider, hard budget guard); privacy (forced); idempotency (watermark);
unattended file moves (archival is reversible + logged); summarization cost on every long turn
(only fires when over the trim threshold; cached; setting-gated with a trim fallback).

---

### Milestone 18 — Semantic Knowledge Graph (Markdown) + Plugin Graph Viewer ✅ (implemented)

**Shipped (commits on `dev`):** Slice 1 — `graph/extractor.py` `extract_triples()` makes one
forced-private, capped LLM call turning a note into `Subject | relation | Object` triples (`parse_triples`
is pure: cleans names, drops self-loops/malformed, honours NONE). Slice 2 — `graph/store.py`
`merge_triples()` materialises them as linked Markdown **entity notes** under `AI/Graph/Entities/`
(frontmatter `type`/`private`; `## Relations` labelled `[[wikilinks]]`; `## Source notes` back-links) —
Obsidian's own graph view renders it. Append-only + idempotent; **sticky privacy** (any private source →
private entity, hidden from non-private queries); `AI/Graph` excluded from the RAG index (derived data).
`graph/job.py` — `build_graph_for_note()` (on-demand) and incremental `build_graph()` (per-note hash
watermark in `AI/Graph/.graph-state.json`, `graph_build_limit` cap, skips the derived `AI/` trees).
Slice 3 — `GET /graph?node=&depth=` serves the local subgraph (`read_subgraph` BFS, depth 1-3). Slice 4 —
plugin `GraphViewerModal` (radial SVG: centre + neighbours, labelled edges; click a neighbour to recentre,
the centre to open its source note) via a **Graph** quick-bar button. Commands: `vault:graph <note>`
(terminal + plugin), `python -m assistant_core --build-graph [--limit N]`, and a nightly hook in the
scheduler gated by `auto_graph_enabled` (default **false** — the highest-cost milestone). Slice 5 —
`tests/test_graph.py` (parse/extract/merge/idempotent/sticky-private/subgraph/job-incremental) +
`/graph` endpoint test; full suite 218 green; plugin `tsc` clean, built, deployed.

**Graph-aware retrieval / Guides (was deferred — now done):** `graph/guide.py` `build_guide()` maps a
topic to an entity (exact → substring → embedder-nearest), pulls its connected cluster via `read_subgraph`
+ the source notes behind those entities, and assembles a **cited** overview in one non-agentic call
(`[[note]]` citations). Command `vault:guide <topic>` (terminal + plugin). Whether private entities are
included in the graph viewer / guides is a setting — `graph_include_private` (default false) — threaded
into `read_subgraph`, the `/graph` endpoint, and `build_guide`.

**Alias / dedup merges (was deferred — now done):** `store.suggest_aliases()` proposes near-duplicate
entity pairs (string signals + embedder cosine); `store.merge_entities()` unions relations/sources/aliases
into the canonical, **repoints incoming `[[alias]]` links** across other entity notes, records the alias
in frontmatter, and deletes the alias note (reversible via rebuild). Command `vault:graph-merge
<canonical> -> <alias>`. Entity notes now carry an `aliases:` field.

**Still deferred:** a propose/commit *review* UI for graph writes (the graph is derived + namespaced +
rebuildable, so it writes directly like the RAG index / OCR sidecars; `merge` is an explicit user command).

**Goal:** an LLM-extracted **entity/relation graph stored as linked Markdown** under `AI/Graph/`, built
**incrementally during the M17 nightly pass**, browsable both in Obsidian's native graph view *and* a
**plugin popup viewer**, and used for entity-centric retrieval. Highest cost/effort — gated on M16+M17
proving their value. Depends on **M17** (the engine) and **M16** (the retrieval substrate).

**Grounding:** the M17 consolidation pass (same off-peak, budgeted, private-forced LLM loop + the
indexer's hash-based change detection so only new/changed notes are processed), M16 hybrid retrieval
(the graph becomes another signal), and the plugin's existing modal/dialog infrastructure in
`obsidian-plugin/ChatView.ts`.

**Slices:**
1. **Entity/relation extraction (dream-time, propose/commit).** Extend the M17 pass: for changed notes,
   extract entities + typed relations (triples) via the LLM (budgeted; private notes → private entities,
   excluded from non-private contexts and any web handoff). Write proposals to `AI/Graph/proposed/`.
2. **Markdown graph store + merge.** Each entity = a note `AI/Graph/Entities/<entity>.md` (frontmatter:
   type, aliases; body: relations as `[[links]]` to other entities + back-links to source notes).
   Alias/dedup resolution via the embedder; merges are judgment-laden → propose/commit. Obsidian's own
   graph view renders it for free.
3. **Graph-aware retrieval.** Extend M16: map a query to entities, pull connected entities' source
   notes, and support "summarize this cluster" answers (a retriever mode / endpoint).
4. **Plugin graph viewer (popup).** A modal in the plugin that renders a **local subgraph** (entity +
   neighbours + source notes) as a force-directed SVG; click a node → open the note or recenter. Data
   from a new `GET /graph?node=…&depth=` endpoint that serves the local subgraph from the Markdown
   store. Subgraph size is capped for render performance.
5. **Tests + docs.** Deterministic extraction tests (fake router → fixed triples → entity notes
   written/merged; alias dedup; a private entity is excluded); `/graph` endpoint test; plugin
   `tsc`/build. Project-State M18 + `AI/Tests/M18-Knowledge-Graph-Tests.md`; mirror.

**Risks:** cost (whole-vault extraction — mitigated by incremental + budget + box-only); graph noise
(propose/commit merges, conservative prompts); privacy (private entities); viewer perf (cap subgraph);
note churn (namespaced under `AI/Graph/`, rebuildable).

**Sequencing:** **M16 → M17 → M18.** M16 ships value alone; M17 ships value alone and builds the engine;
M18 reuses both. Each milestone keeps the full test suite green and follows propose/commit + privacy +
zero-cost-first discipline.

---

### Milestone 19 — Image, Handwriting & Excalidraw Processing ✅ (implemented)

**Shipped (commits on `dev`):** Slice 1 — `media/excalidraw.py` indexes a drawing's `## Text Elements`
(block-ids stripped, JSON-scene fallback) instead of the compressed scene JSON, so Vault QA covers
Excalidraw sermon notes (verified: 20.7K chars from a real note, zero noise). Slices 2/3/5 —
`media/ocr.py` `OcrEngine`: for each image embed (`![[img.png]]` / `![](path)`), OCR via a **free
multimodal model** (`make_vision_fn` picks a `multimodal`-tagged provider; `describe_image()` added to
the OpenAI adapter) with a **local tesseract fallback**; one tuned prompt handles printed text *and*
handwriting. **Privacy:** a `private` note's images go only to no-train multimodal providers or local
tesseract. Slice 4 — results written as an **additive, AI-derived sidecar** `AI/Derived/<note>.ocr.md`
(frontmatter `ai-derived: ocr`, backlink to source; original never touched) which the M11 index picks up
(`AI/Derived` is not excluded). Slice 6 — `vault:ocr <note>` works in the terminal and from the plugin
(server intercept; re-indexes the sidecar). Slice 7 — `tests/test_excalidraw.py` + `tests/test_ocr.py`
(embed parse, vision/tesseract paths, privacy threading, no-train selection, additive sidecar) +
server-endpoint test. Vision/tesseract callables are injectable so it's all tested without a model or the
tesseract binary. `pytesseract`/`Pillow` are optional (commented in requirements; Excalidraw needs neither).

**Deferred:** a dedicated plugin "Process images" button (the `vault:ocr` command is already reachable
from the plugin chat) and auto-OCR on image change (OCR is on-demand).

**Goal:** make notes that are **images, scanned handwriting, or Excalidraw drawings** first-class —
their content becomes searchable and answerable in Vault QA. **Zero added cost**: typed Excalidraw text
is parsed directly, and image/handwriting OCR reuses the **free multimodal models** the registry already
has (Groq llama-4-scout/maverick, Gemini Flash, NVIDIA vision) — no new paid service. Depends on **M11**
(RAG indexing) and **M16.7** (which tags which models are `multimodal`).

**Grounding:** the vault has many `*.excalidraw.md` files (e.g. sermon notes) and image attachments;
`rag/indexer.py` already walks notes and records chunks; `rag/service.py` re-embeds changed notes; the
router can route to a `multimodal`-tagged provider; M9 propose/commit governs any write-back.

**Slices:**
1. **Excalidraw text (zero-cost, exact).** Parse the embedded Excalidraw JSON scene and pull all text
   elements (typed labels) directly — no OCR. Index that text so Vault QA covers drawings. Most of the
   value for the least cost.
2. **Image OCR / captioning.** Detect notes with embedded images (`![[*.png|jpg|jpeg|webp]]`,
   attachments). Send the image to a **free multimodal model** (vision route) with an OCR+describe
   prompt; **local `tesseract` fallback** when offline or for printed text. Returns extracted text +
   a short description.
3. **Handwriting.** Same vision path, prompt tuned for handwriting (vision models beat classic OCR
   here); image-only notes (a photo of a page) are treated as handwriting candidates.
4. **Indexing integration.** Store extracted text as an **additive, clearly-AI-generated sidecar**
   (e.g. an `<!-- ai-ocr -->` block or `AI/Derived/<note>.ocr.md`, never overwriting the original —
   propose/commit), then feed it to the M11 index so the image's content is retrievable. Watcher hook
   re-runs on change.
5. **Privacy.** A `private` note's images route **only to no-train multimodal providers**, or local
   `tesseract` only — honoring the M10 rule (image content can't leak to a training provider).
6. **UX.** Plugin: a "Process images in this note" action + a Vault QA that can cite image-derived text.
   Terminal: `vault:ocr <note>`.
7. **Tests + docs.** Excalidraw JSON → text (fixture); fake vision `generate` → extracted text indexed;
   private image forces no-train / local; sidecar is additive (original untouched). Project-State entry
   + `AI/Tests/`; mirror.

**Risks:** vision accuracy on messy handwriting (keep the original; mark output AI-derived; user can
correct); cost/RPD of vision calls (only on demand or for changed notes; Excalidraw needs none);
`tesseract` is an optional dependency (graceful skip if absent).

---

### Milestone 20 — Agent Planner Robustness ✅ (implemented)

**Goal:** stop the agent over-continuing and replanning, surfaced by the T5.01 run (it generated the
research prompt correctly, then looped for 6+ steps "finishing the test", and in another run built a
whole note section-by-section over ~10 min). Partly mitigated already (M-prompt rules + server-side
`vault:` interception); this milestone makes it structural.

**Shipped (commits on `dev`):** Slice 1 `TERMINAL_TOOLS` in `agent_loop.py` — after a deliverable tool
(`generate_research_prompt`) runs, the loop returns its output and stops instead of looping. Slice 2
`vault:research` reuses the M7 handoff round-trip: `server/core.py` returns a `HandoffResponse` so the
session enters the await-paste-back state (terminal `---end` / plugin **Submit response**), then
synthesises the pasted web-AI reply. Slice 3 **externalized task/planner state** —
`assistant_core/task_ledger.py` `TaskLedger` keeps goal + per-tool checkpoints **outside** the model and
re-injects a compact `[TASK STATE]` block into the system prompt every step; on a mid-turn provider
switch it adds a "you just took over — continue, don't restart" note, so a switched-to model resumes the
same plan instead of replanning from chat history. The ledger is also mirrored to
`AI/System/Task-State.md` each step (RAG-excluded, non-`pending` path → no index spam / no watcher loop)
so the user can watch the stages live and resume after a crash. The research paste-back
(`/chat/handoff-return`) **saves the verbatim research first** (deterministic `import_research` →
`AI/Research/<date>-<slug>.md`, full text + citations intact), then **summarises with ONE non-agentic LLM
call** and appends a `## Related notes` section built **deterministically** from `rag.relevant_notes`
(real index neighbours only). The summary call runs no tools, so the model can't invent wikilinks or loop
on repeated searches — the T5.01 retest showed the agent-loop version fabricating `[[…]]` links to notes
that don't exist and re-searching 4+ times. Shared `research_roundtrip.py` (`save_research_verbatim` /
`summarize_research` / `append_related_notes` / `generate_note_title`) keeps the server and terminal
identical. `generate_note_title` is one more non-agentic call that names the note in 1-4 words
(`ImportResearchTool(title_fn=…)` via `ToolRegistry(router=…)`), so the file is
`AI/Research/<date>-rocket-mass-heater.md` instead of `…-a-rocket-mass-heater-is-a-wood-burning.md`;
forced-private and falls back to the old first-line slug if it fails. Also fixed a
latent `extract_vault_commands` bug that truncated `vault:create`/`vault:update` bodies at the first blank
line — multi-paragraph notes saved only their title. Slice 4 tests:
`tests/test_task_ledger.py` (incl. persistence) + `tests/test_server_endpoints.py` (paste-back synthesis) +
`AgentLoopTaskLedgerTests` (ledger injected, accumulates, switch flagged) and the prior
`AgentLoopTerminalToolTests`. Suite 143 green.

**Slices (as planned — all shipped):**
1. **Terminal-tool semantics (done in prompt; make it enforced).** `vault:research` is a deliverable:
   call → present prompt → stop. The system prompt now says so; add a loop-side guard so that after a
   "deliverable" tool runs, the loop returns its output instead of looping for more commands.
2. **Wire `vault:research` into the existing paste-back round-trip.** The round-trip is already
   *designed* (ChatGPT didn't know this): research question → generate WebUI prompt → **wait for the
   user to paste the web-AI response** (terminal: type `---end`; plugin: click the **Submit response**
   button) → think about / synthesise the response. The gap is that the `vault:research` *tool* just
   returns a prompt string and does **not** put the session into the await-paste-back state the M7 web
   handoff uses — so there's no submit point after it. Fix: after `vault:research` produces the prompt,
   enter the same handoff-awaiting state (reuse `handoff-awaiting-response` / `/chat/handoff-return`),
   then on paste-back summarise/answer it and offer to save with `vault:create`. No new import tool —
   reuse the handoff machinery that already exists.
3. **Externalized task/planner state** (ChatGPT's main recommendation). Endpoint *switching* works
   (8–9/10) but execution continuity is weak (4–5) because a switched-to model replans from
   conversation history. Maintain a small task object (goal / plan / completed / current step /
   remaining) **outside** the model and inject it on every step + on provider handoff, so a model
   switch resumes the same plan instead of reinventing it. Add a tiny per-tool checkpoint.
4. **Tests + docs.**

**Source:** `AI/Tests/in progress/test5.01/` (real T5.01 logs + ChatGPT "Agent Behavior Analysis").

---

## Roadmap M21–M28 — closing the capability gaps (2026-07-01 review)

From a review of what the assistant does vs. how Obsidian is used and what Logos Bible software offers,
12 gaps were identified. These milestones fill them, sequenced by **value × dependency**: reach the web
(M21) → ingest real sources (M22) → make the graph answer questions (M23) → make Scripture first-class
(M24) → make it all trustworthy (M25) → then precision search, audio, and retention (M26–M28). Every
milestone keeps the standing discipline: **zero-cost-first** (free tiers + local), **privacy-forced**
(private content never leaves the machine / no-train providers only), **propose/commit** for anything
destructive, and full test suite green. Gap numbers refer to the review list.

### Milestone 21 — Web-Capable Research ✅ (implemented) — *gaps 1, 12, part of 5*

**Shipped (commits on `dev`):** `assistant_core/web/` — `search.py` `web_search()` (keyless DuckDuckGo
HTML by default, Tavily if `tavily_api_key` set, injectable + never raises), `fetch.py` `web_fetch()` +
`html_to_text()` (main-text extraction; `trafilatura` if installed, dependency-free fallback otherwise),
and `research.py` `run_web_research()` — the orchestrator: **privacy hard-block** (a `private` turn writes
nothing and never hits the web), search → fetch top-N (bounded by `web_max_results`/`web_max_fetches`) →
**one non-agentic** cited synthesis (cites only fetched URLs) → saves each page **verbatim** plus a
`Summary.md` under `AI/Research/<date>-<slug>/` (LLM-titled) → appends real related notes. Command
`vault:webresearch <question>` in the terminal and plugin (server intercept). Config
`web_research_enabled` (default true) / `web_max_results` / `web_max_fetches` / `tavily_api_key`. The
manual `vault:research` round-trip is **unchanged** as the fallback. Tests: `tests/test_web.py`
(search parse + redirect decode + injected fn, fetch html→text + failure-safe, orchestrator saves
summary+verbatim sources+citations, **private blocked writes nothing**, disabled/no-results) + a
server private-block test. Full suite 233 green.

**Multi-provider search (added):** `web/providers.py` makes search **config-driven like the model
registry** — `web_search_order` is tried until one returns results, skipping any whose key/URL isn't set.
Keyless **DuckDuckGo** (ddgs lib or HTML scrape) and self-hosted **SearXNG** cost nothing; **Brave /
Serper / Tavily / Exa / Google CSE** enrol automatically when their key is configured. All adapters are
dependency-free (urllib) and degrade gracefully. Also: `vault:search` gained plugin-configurable folder
scope (`search_exclude_folders` / `search_include_folders`).

**Deferred:** an allow/deny domain list + explicit robots.txt handling (currently best-effort keyless
search + graceful skip); a plugin "Research the web" button (the `vault:webresearch` command is already
plugin-reachable).

**Goal:** give the assistant real internet access so `vault:research` **gathers and saves autonomously
with citations** instead of the manual copy/paste round-trip. Highest unblocking value — the user asked
for this directly.

**Grounding:** the M20 research round-trip (`research_roundtrip.py`, verbatim save + summary + real
related notes), the router's privacy routing, `import_research`, and `provider_tracker._fetch` (an
existing plain HTTP GET to build on).

**Slices:**
1. **Web tools.** `WebSearch` (keyless-first — DuckDuckGo/SearXNG; optional Brave/Tavily key) + `WebFetch`
   (fetch + readability-extract the main text). Config-gated keys; graceful when absent.
2. **Autonomous research.** `vault:research <q>` runs search → fetch top-K → synthesise **with inline
   source URLs** → save each fetched page verbatim under `AI/Research/<topic>/` + a synthesis note (reuse
   `import_research` + deterministic related notes). Bounded (max fetches / token budget).
3. **Privacy.** A `private` turn NEVER hits the web; only the query string leaves (never vault content);
   respect robots and an allow/deny list.
4. **Trust.** Every claim cites a **fetched** URL only — no citation the assistant didn't actually load.
5. **Tests + docs.** Injectable fake search/fetch; a private turn is blocked from the web; citations map
   to fetched pages; `AI/Tests/M21-Web-Research-Tests.md`; mirror.

**Risks:** paywalls/JS pages (readability + graceful skip); rate limits (cache + keyless-first); privacy
(hard block on private); fabricated citations (only cite fetched URLs). Keeps the manual paste path as a
fallback.

### Milestone 22 — Document Ingestion (PDF / EPUB / DOCX) ✅ (implemented) — *gap 2, feeds 6*

**Shipped (commits on `dev`):** `assistant_core/ingest/` — `extract.py` `extract_document()` pulls
page/section-structured text from `.pdf` (pypdf), `.epub` (ebooklib), `.docx` (python-docx), and
`.txt`/`.md` (no dependency); heavy libs are optional + lazily imported and a missing one returns a clear
error instead of raising. `ingest.py` `ingest_file()` writes a clearly-AI-derived
`AI/Library/<date>-<slug>.md` with one `## Page N` / `## Section` block per source page (provenance
anchors), indexes it immediately when a live RAG service is passed (else the watcher picks it up), and
optionally feeds the M18 graph (`ingest_to_graph`). Command `vault:ingest <file>` (terminal + plugin;
server intercept). `AI/Library` is indexed (not excluded), so ingested docs answer in Vault QA.
`tests/test_ingest.py` (txt/md extraction, missing/unsupported graceful, multi-page ingest writes page
anchors + frontmatter, extraction-error reported, real end-to-end). Full suite 257 green.

**Deferred:** scanned-PDF OCR fallback (needs `pdf2image` + poppler — currently a text PDF with no
extractable text reports "scanned? OCR not enabled"); an auto-ingest watched drop-folder (ingest is
on-demand via `vault:ingest` for now).

**Original plan (for reference):**

**Goal:** pull real documents — reference works, books, articles, handouts — into the searchable vault.
The single biggest step toward Logos-style *"reason over a library,"* and it feeds the knowledge graph so
it becomes a real Factbook.

**Grounding:** M11 RAG (chunk + embed + index with hash-change detection), M19 OCR (scanned PDFs → free
multimodal / tesseract), the M18 graph extractor, the watcher.

**Slices:**
1. **Extractors.** PDF (pypdf/pdfminer text; OCR fallback for scans via M19), EPUB (ebooklib), DOCX
   (python-docx) — all optional deps, graceful skip if absent.
2. **Ingest.** `vault:ingest <file>` → extract → write a clearly-AI-derived `AI/Library/<name>.md` with
   **page/section anchors** → index. Large docs paginated.
3. **Incremental + watcher.** A watched drop-folder auto-ingests new/changed docs (box-only).
4. **Graph feed.** Optionally run M18 extraction over ingested docs so entities/relations from the library
   populate the graph (gap 6).
5. **Provenance.** Keep page/section anchors so later citations point to an exact location.
6. **Tests + docs.** Per-format fixtures; anchors preserved; index integration; `AI/Tests/M22-*`; mirror.

**Risks:** extraction quality (mark AI-derived, never overwrite originals); OCR cost (scans only, on
demand); large-file memory (stream/paginate); optional dependencies (documented, graceful).

### Milestone 23 — Graph-Aware Retrieval & Guides ✅ (delivered under M18)

**Status:** the M23 scope shipped with **M18** — `vault:guide <topic>` (query → entity → connected
cluster + source notes → cited overview), embedder-based **alias/dedup** (`suggest_aliases` /
`vault:graph-merge`), and the entity browser. M22's ingested documents feed the same graph. See the M18
entry above. *Remaining nicety (deferred): a dedicated "graph-context" retriever mode inside Vault QA
beyond `vault:guide`.*

**Original goal (for reference):** turn the knowledge graph from a viewer into an **answer engine** —
*"give me everything about X, organised."*

**Grounding:** M18 `graph/store.read_subgraph`, M16 hybrid retrieval, M11 Vault QA, M22 ingested sources.

**Slices:**
1. **Query → entities.** Map a question to graph entities (embedder + name match); pull the connected
   cluster's source notes/documents.
2. **Guide assembly.** `vault:guide <topic>` gathers definition + relations + source notes + related +
   open questions into one assembled, **cited** answer/note (reuse RAG + graph).
3. **Alias/dedup merges** (deferred M18 item). Embedder-based entity-merge proposals (`RMH` ≈
   `Rocket Mass Heater`) — propose/commit.
4. **Retriever mode.** Vault QA can pull graph-connected context, not just vector hits.
5. **Tests + docs.** Query→entity mapping, guide assembly, a merge proposal; `AI/Tests/M23-*`; mirror.

**Risks:** cluster sprawl (cap subgraph); wrong merges (propose/commit + conservative threshold); cost
(cached, box-only).

### Milestone 24 — Scripture Intelligence ✅ (implemented) — *gaps 3, 8*

**Shipped (commits on `dev`):** `assistant_core/scripture/` — `refs.py` parses/normalises Bible
references anywhere in text (66 books + common abbreviations + ordinal forms; `1 Jn 2:18` → `1 John 2:18`,
ranges preserved), with `parse_refs` / `parse_refs_struct` / `refs_overlap` / `normalize_ref`.
`passage.py` `find_passage_notes()` gathers every note whose references **overlap** a target passage
(verse-range aware, not exact-string; derived `AI/` trees skipped) and `build_passage_guide()` assembles a
**cited** overview in one non-agentic call. Command `vault:passage <ref>` (terminal + plugin).
`tests/test_scripture.py` (ref forms, dedupe/non-refs, normalise + overlap, passage-note finding, guide,
bad-ref/no-notes). Full suite 266 green.

**Deferred:** registering passages as first-class graph entities (currently found by scan on demand);
original-language help (needs a license-clean free source — the stated zero-cost boundary).

**Original plan (for reference):**

**Goal:** make Bible references **first-class** — the core of the user's sermon/study work — and a
**Passage Guide** that assembles everything known about a passage. Notes-first (not a licensed-library
clone of Logos).

**Grounding:** M18 graph (references as a dedicated entity type), M23 Guide, M11 RAG, the vault's sermon /
Excalidraw notes (M19).

**Slices:**
1. **Reference detection.** Parse + normalise scripture refs (`1 John 2:18`, `1 Jn 2:18-20`) anywhere; a
   canonical entity per book/chapter/verse(-range).
2. **Passage linking.** Every note/source touching a passage links to its reference entity; cross-links
   between related passages.
3. **Passage Guide.** `vault:passage <ref>` assembles your notes + ingested resources + graph for that
   passage (reuse M23).
4. **Original-language help** *(stretch/deferred).* Only if a free, license-clean source exists; otherwise
   explicitly document the boundary vs. Logos.
5. **Tests + docs.** Ref-parsing fixtures (ranges/abbreviations), linking, passage guide; `AI/Tests/M24-*`.

**Risks:** ref-parsing edge cases (ranges, abbreviations, versification); scope creep vs. Logos (stay
notes-first); no licensed texts (a stated zero-cost boundary, not a bug).

### Milestone 25 — Provenance & Citations ✅ (implemented) — *gaps 5, 10*

**Shipped (commits on `dev`):** the source-recording foundations were already in place — M17 consolidation
facts, M18 graph `## Source notes`, M21 web-research citations, and M22 ingested-doc page anchors each
record where content came from. M25 adds the **audit tool**: `assistant_core/provenance.py`
`find_sources()` scores which vault notes support a claim by key-term overlap (stopwords/short words
dropped; log trees excluded) and flags a claim as **unsourced/weakly-sourced** when no note covers a
majority of its terms. Command `vault:sources <claim>` (terminal + plugin). `tests/test_provenance.py`
(term extraction, supporting-note ranking, unsourced claim, episode exclusion). Full suite 286 green.

**Deferred:** inline per-sentence citation rendering inside every Vault QA answer (QA already returns
cited source chips; guides cite `[[notes]]`).

**Original plan (for reference):**

**Goal:** a **trust layer** — every generated fact, graph relation, summary, and answer carries a citation
back to its source (note / document+page / passage / URL). Makes the whole system auditable.

**Grounding:** M17 consolidation facts, M18 graph `## Source notes`, M21 web sources, M22 document anchors.

**Slices:**
1. **Source tags.** Consolidation facts and graph relations record their source note + line; web/doc
   sources record URL / page anchor.
2. **Cited output.** Vault QA and Guides render compact inline citations linking to the exact source.
3. **Provenance audit.** `vault:sources <fact|answer>` traces origin and flags **unsourced** claims.
4. **Tests + docs.** Source tags round-trip; unsourced claim flagged; `AI/Tests/M25-*`; mirror.

**Risks:** citation verbosity (compact linked form); retrofitting pre-existing facts (best-effort, forward
from here).

### Milestone 26 — Structured & Exact Search ✅ (implemented) — *gap 9*

**Shipped (commits on `dev`):** `assistant_core/query.py` `structured_search()` — a small grammar ANDing
`tag:x`, `path:"…"`, `fm:key=value`, `"exact phrase"`, bare words (all must appear), and `A NEAR/n B`
(within N words). Pure/deterministic (no LLM/embeddings); episode/log trees skipped. Command
`vault:query <expr>` (terminal + plugin). `tests/test_query.py` (tag/path/fm/phrase/words/NEAR/combined/
episode-excluded). Full suite 273 green.

**Original plan (for reference):**

**Goal:** precision search to complement semantic RAG — field / frontmatter / tag / date / phrase /
proximity queries (Dataview-like), e.g. *"notes citing ESV within 2 words of 'antichrist'."*

**Grounding:** the RAG index metadata (tags, links, frontmatter, `note_path`), M16 graph tags,
`search_vault`.

**Slices:**
1. **Query language.** A small structured grammar: `tag:`, `path:`, `<frontmatter-field>:`, `"phrase"`,
   `NEAR/n`, boolean.
2. **`vault:query`.** Run it; optionally blend with semantic ranking.
3. **Plugin.** A query box + saved queries.
4. **Tests + docs.** Grammar fixtures, proximity, field match; `AI/Tests/M26-*`; mirror.

**Risks:** grammar creep (keep minimal); performance (index-backed, capped results).

### Milestone 27 — Audio Transcription ✅ (implemented) — *gap 4*

**Shipped (commits on `dev`):** `assistant_core/media/audio.py` — `transcribe_audio()` runs **local**
`faster-whisper` (optional dep; free, offline — audio never leaves the machine; graceful message if not
installed) and `transcribe_to_sidecar()` writes an additive `AI/Derived/<name>.transcript.md` the M11
index picks up (original audio untouched; resolves an audio file by bare name too). The transcriber is
injectable, so it's fully tested without the model. Command `vault:transcribe <audio>` (terminal +
plugin). `tests/test_audio.py` (injected transcriber, missing/failure safe, additive sidecar, name
resolution). `faster-whisper` noted optional in requirements. Full suite green.

**Original plan (for reference):**

**Goal:** sermon/lecture **audio → searchable text**, first-class like OCR — high value for the user's
preaching workflow.

**Grounding:** the M19 media pattern (additive sidecar + index + privacy), free **local** Whisper
(`faster-whisper`), the watcher.

**Slices:**
1. **Transcribe.** `vault:transcribe <audio>` via local `faster-whisper` (offline, free) →
   `AI/Derived/<name>.transcript.md` → index.
2. **Timestamps / segments** *(stretch).* Segment with timestamps for navigation.
3. **Privacy.** Audio stays **local** (Whisper is local) — never uploaded to any provider.
4. **Tests + docs.** Injectable fake transcriber; additive sidecar; index integration; `AI/Tests/M27-*`.

**Risks:** Whisper compute (box CPU/GPU, on demand); optional dependency; accuracy (mark AI-derived, keep
the audio).

### Milestone 28 — Study Reinforcement / Spaced Repetition ✅ (implemented) — *gap 11*

**Shipped (commits on `dev`):** `assistant_core/study/cards.py` — `generate_cards()` (one forced-private
LLM call → Q/A flashcards, parsed), a deck in `AI/Review/deck.json`, `add_cards()` (dedup, due today),
`sm2()` (SM-2 scheduling: grade 0-5, ≥3 passes, expanding intervals, ease floor 1.3), `due_cards()`, and
`review()` (grade → reschedule → persist). Commands `vault:cards <note>` (generate from a note) and
`vault:review` (show what's due). `tests/test_study.py` (parse, forced-private generation, dedup, SM-2
progression + fail-reset, due/review lifecycle). Full suite 282 green.

**Deferred:** a plugin flip-card review UI (reuse the Memory-review panel pattern) — for now `vault:review`
lists due cards and grading is via the API/`review()`.

**Original plan (for reference):**

**Goal:** help the user **retain**, not just capture — generate review questions/flashcards from notes and
schedule active recall. Closes the loop from "knowledge captured" to "knowledge learned."

**Grounding:** the memory system, the LLM (card generation), the plugin's review-panel pattern (M17
Slice 4), the in-process scheduler (M16.7/M17).

**Slices:**
1. **Card generation.** From a note/topic, generate Q/A cards → propose into `AI/Review/` (propose/commit).
2. **Scheduling.** SM-2-style intervals; a due-cards queue in a small JSON state.
3. **Plugin review UI.** Flip/grade cards (reuse the memory-review accept/reject pattern).
4. **Tests + docs.** Card generation (fake router), interval scheduling, due-queue; `AI/Tests/M28-*`.

**Risks:** card quality (user edits/rejects); scheduling state (simple JSON); scope (start minimal —
Bible-verse and definition cards first).

---

### Deferred / Long-Term

- **Task Harvester** — scan vault-wide for `- [ ]` tasks into a Todo note. Low priority; can be triggered manually with `vault:search - [ ]` in the meantime.
- **Multi-Agent Systems** — researcher/planner/coder/reviewer roles. Phase 3.

---

### Milestone 29 — Restructuring propose-and-approve ✅ (implemented)

The agent can now **reorganise the vault on request** — but never on its own. `vault:copy`,
`vault:move`, `vault:trash`, and `vault:mkdir` were previously hard-blocked in the agent loop
(so a plain-language "move/rename/remove this note" either refused or, before the fix, looped on
the block). They now use the same **propose/commit** discipline as edits: the agent emits the
command, the loop stages it as `AgentContext.pending_restructure` and **ends the turn** (never
auto-runs, never retries), the server returns it as a `proposal`, and the plugin renders a
one-click **Approve / Reject** card. Approve re-sends the exact command, which executes via the
direct `system` path; nothing changes until then (`trash` stays recoverable → `.trash/`). System
prompt (×3) reworded to "propose-and-approve"; `_restructure_proposal()` parses op + src/dst.
Tests: proposal generation ends the turn in one step + move-path parsing (294 green). Verified
live in the plugin (natural-language move → card → Approve → file moved).

---

### M30 — Model Robustness & Anti-Hallucination ✅ (implemented)

Make the assistant reliable across the diverse free-tier model pool — stop the fake
`[[links]]`, stop mistaking the open note for pasted input, and verify facts before trusting them.
Behavior-preserving; 302→323 tests.

- **Context framing** (`server/core.py` `/chat`): injected notes are wrapped as labelled
  `=== BACKGROUND … ===` / `=== USER MESSAGE (respond to THIS) ===` so a model no longer treats the
  open note as the user's message (the "typed *test* → 'I see you posted this note'" bug).
- **Fake-`[[link]]` killer** (`assistant_core/links.py`): `neutralize_dangling` resolves every wikilink
  against the real vault and strips dead ones to plain text + a footnote of what was removed. Applied in
  `create_note`/`update_note` (all write paths). Config `link_validation: strip|flag|off` (default strip).
  `get_linked_notes` reuses the shared resolver (single source of truth).
- **Capability- & tier-aware routing** (`providers/model_registry.py`): `derive_tier()` +
  `ModelSpec.tier` (small/mid/large from the model id); `route_order(task=…)` + `TASK_PROFILE` keep
  factual tasks (qa/research/graph) on larger models and tiny models last. Neutral when no task given →
  M10 order unchanged. Threaded via `router.generate(task=…)` from the QA + edit paths.
- **Tier-aware prompting** (`providers/provider_router.py`): a per-tier addendum appended to the selected
  model's system prompt — small models get hard "use only provided context; never invent notes/links/
  quotes/citations; say 'I don't know'" rules; large models are left alone.
- **Verification pipeline** (`assistant_core/verify.py` `guard_answer`): if a QA answer isn't grounded in
  the vault (M25 provenance), escalate to a larger model, then web-search real citations (M21) and attach
  them; flag ⚠ only if still unverifiable. **Private content never hits the web** (flag only). Wired into
  server Vault QA. Config `hallucination_guard: escalate_web|flag|off` (default escalate_web).
- **Deferred:** self-consistency sampling (`self_consistency_k`, config stub).
- **Tests:** `test_links.py`, `test_verify.py`, additions to `test_routing.py` / `test_chat_context.py`.

### M31 — Section-Chunked Large Edits ✅ (implemented)

A large selection no longer truncates: `editing.split_for_edit()` splits it at paragraph boundaries,
`server/core.py` `_handle_edit` edits each section under the token cap and reassembles them into **one**
proposal (per-section failure keeps that section's original). Small selections keep the single-call path.
Tests in `test_editing.py` + a server reassembly test. 327 tests green.

---

### M32 — Deterministic Math ✅ (implemented)

A free model asserted "4 + 6 = 12" and doubled down. Fix: never let the model guess arithmetic.
- `assistant_core/tools/calc.py` — `CalcTool` (safe AST evaluator; `vault:calc`) + `maybe_answer_arithmetic()`.
- `server/core.py` `/chat` answers a plain arithmetic query (`4 + 6 =`, `what is 3*7?`) **deterministically
  before any model runs** (`provider=system`) — always correct, can't be argued wrong.
- `provider_router` clamps temperature for factual tasks (`TASK_MAX_TEMP`: math=0.0 … qa/edit=0.3).
- System prompt: use `vault:calc` for all arithmetic. Live-verified (4+6=10, 3*7=21, (2+3)*4=20).

### M33 — Agent Full-Command Access + Autonomous Web Research ✅ (implemented)

Root cause of "it does the webui paste-thing instead of webresearch": the system prompt *forbade* the
agent from emitting the rich command set, and those commands lived only as server/terminal intercepts.
- `assistant_core/vault_dispatch.py` `run_extended()` — gives the agent loop the rich commands
  (webresearch / ingest / query / sources / passage / guide / ocr / analyze / graph / transcribe / cards /
  review), reusing existing handlers; inject-vs-terminal classification; **web refused on private turns**.
- `agent_loop` routes emitted non-basic `vault:` commands to `run_extended`; `AgentContext` gains
  `config` + `rag` (threaded from server/terminal/watcher).
- Prompt rewritten: the agent MAY use these; **use `vault:webresearch` for web lookups** (not
  `vault:research`/webui). `import`/`discover`/`reindex`/`test`/`run-script` stay user-only; restructuring
  stays propose/commit. Live-verified: "look on the web for…" → autonomous cited research, no paste-prompt.
- *Deferred:* deduping the server/app intercepts through `run_extended` (internal cleanup; overlaps the
  clean-architecture refactor).

---

## Post-v1.0 — Release Status & Next Work

*This section is the resume point. Everything above documents what was built; this documents where the
project stands after the public release and what the next session should pick up.*

### Release — done 2026-07-03 ✅
- **Public repo:** https://github.com/DocGRD/AI-Assistant (visibility: public). `main`, `dev`, and tag
  `v1.0.0` all point at a single **clean-slate commit** authored as
  `Glenn Dewar <203316586+DocGRD@users.noreply.github.com>` (ID-prefixed GitHub noreply — credits the
  contribution graph while hiding the real email). The Linux box clone is synced to the same commit; the
  service is online.
- **GitHub Release:** a **pre-release** titled "beta v1.0.0" on tag `v1.0.0`, with the three plugin assets
  attached — `main.js` (51,385 B), `manifest.json` (397 B), `styles.css` (21,662 B). Pre-release is the
  correct state for BRAT (BRAT reads the latest release including pre-releases).
- **Distribution:** **BRAT** → *Add beta plugin* → `DocGRD/AI-Assistant` → enable **AI Assistant** → point
  its ⚙ settings at the Python service. `LICENSE` = MIT; `obsidian-plugin/versions.json` maps `1.0.0` →
  minAppVersion `1.4.0`.
- **One open release chore:** the repo **Topics** were not set. Add them via the repo page → About ⚙ →
  Topics: `obsidian obsidian-plugin ai rag llm local-first self-hosted knowledge-management second-brain`.
  (Helps GitHub/Google discovery; the user is on no social platforms, so organic search + BRAT is the
  current reach.)

### Discovery next step (deferred): official Obsidian Community-plugins directory
The built-in **Community plugins** browser inside Obsidian is the highest-reach, no-social-account way to
be found. It is **not yet submitted**, and there are three real blockers to resolve first:
1. **Dedicated plugin-only repo required.** The directory's validation expects `manifest.json` at the
   **repo root**; this repo is a Python-service + plugin **monorepo** (plugin lives under
   `obsidian-plugin/`). A separate companion repo containing just the plugin (manifest at root + a release
   with `main.js`/`manifest.json`/`styles.css`) is needed.
2. **Plugin id collision.** The current id `ai-assistant` is **already taken** in the directory
   (5,337 plugins as of 2026-07-03). A new **unique id** must be chosen for the directory submission
   (BRAT is unaffected — it installs by repo, not id).
3. **Submission is a review PR** to `obsidianmd/obsidian-releases` from the user's own GitHub account
   (adds an entry to `community-plugins.json`); review can take weeks.
- Tooling note: `gh` CLI **2.96.0 is installed** on the Windows box (`C:\Program Files\GitHub CLI\gh.exe`)
  but was **never authenticated** — the v1.0.0 release was published via the GitHub web UI. A future
  session can `gh auth login` (interactive, user-run) and then drive release/topic/PR steps.

### Deferred: clean-architecture refactor (scoped 2026-07-03, NOT started)
A "full rewrite" was discussed, scoped, then **cancelled before any code changed** — the plan below is the
agreed direction so it can resume cold without re-deriving.
- **Direction chosen (by the user):** an **in-place, behavior-preserving refactor** optimizing for
  **clean architecture / maintainability** — explicitly *not* a ground-up rewrite. The 302-test suite is
  the safety net and gets extended where the refactor exposes seams.
- **Hard constraints:** freeze the **HTTP contract** (the plugin depends on the exact endpoints/shapes) and
  the **vault on-disk layout** (`AI/Memory/Episodes/…`, `AI/System/…`, index at `data/vault_index/`, etc.).
  External behavior must be identical before and after.
- **Diagnosis (milestone-accretion smell):** two God files —
  - `assistant_core/server/core.py` (**1150 LOC**): the `/chat` handler alone is **~500 lines** (~452→956)
    fusing HTTP transport + context assembly + routing + agent loop + edit/QA/handoff branching.
  - `assistant_core/app.py` (**1008 LOC**): simultaneously the composition root, the headless-runtime loop,
    and venv/handoff plumbing.
  - plus **13 orphan top-level modules** dumped at `assistant_core/` root with no cohesive home:
    `agent_loop`, `vault_commands`, `editing`, `scripts_runner` (→ an **agent** package);
    `consolidation`, `scheduler`, `episodes`, `task_ledger` (→ **memory/autonomy**);
    `research_roundtrip` (→ **web/research**); `query`, `provenance` (→ **knowledge/rag**);
    `paths`, `diagnostics` (→ a **platform** package).
- **Target sketch:** a **thin `server/`** (routes + pydantic schemas only) sitting over an extracted
  **service layer** (chat / edit / qa / settings / restructure services); the orphan modules regrouped into
  the cohesive packages named above; `app.py` split into a composition root + a headless runner. Keep
  already-cohesive packages (`providers`, `rag`, `graph`, `media`) intact.
- **Open scoping decisions — NOT finalized** (the user dismissed these questions, then cancelled). Re-confirm
  both **before** writing any code:
  1. **Scope:** Python service only, or backend **+** the TypeScript plugin (`ChatView.ts` has also grown
     large, but has far less automated coverage).
  2. **Depth:** full layered re-architecture (regroup everything; high import churn across ~90 files +
     36 test modules), or focused (decompose the two God files + rehome the 13 orphans only; ~80% of the
     clarity, ~half the churn).
- **Execution discipline (agreed):** slice it so the full **302-test** suite is green after every slice;
  after the refactor, run the live **GUI/box E2E** pass (see the GUI-harness and Linux-box deploy notes)
  before re-tagging a new version.

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
