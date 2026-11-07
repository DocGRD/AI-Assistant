# Web Partner Protocol

*Status: planning / M43 target. Defines the structured handoff between Loremaster and free web-portal models (Gemini, Claude, ChatGPT, Grok) so those models can request vault tools without a paid API.*

**Related:** [`Connector-Surface.md`](Connector-Surface.md) (Path 2 — Loremaster *as* a connector). This document is **Path 1** — vault-native paste/continue that works on phone and laptop with no browser extension.

---

## Purpose

Give the user a first-class way, from the Loremaster sidebar, to:

1. Package a question + vault context + a **tool catalog** for a web AI.
2. Open that package in Gemini / Claude / ChatGPT / Grok (any browser, including phone).
3. Paste the web AI’s reply back into the sidebar.
4. Have Loremaster **execute allowlisted tools**, inject real results, and offer **Continue** until the partner emits a final answer.
5. Optionally save the transcript under `AI/Research/`.

This evolves today’s `vault:research` + `WebUI-Prompt.md` handoff into a **tool-aware multi-round protocol**. It does **not** drive web UIs with automation and does **not** require a Chrome extension (those are optional later; see Connector-Surface and desktop webview notes).

---

## Design principles (non-negotiable)

| Principle | Rule |
|-----------|------|
| **Zero cost** | Free web portals only; no paid API required for this path. |
| **Privacy** | Notes/turns marked `private` never enter a web package unless the user **explicitly opts in for that handoff**. |
| **Honesty** | Web partners are told they have no direct vault access. They must not invent note contents. Tool results are the only ground truth. |
| **Allowlist** | Only read-oriented tools in Phase 1. Writes are never executed from a partner reply; at most they become Approvals proposals (later phase). |
| **Caps** | Max tool rounds per session, max tools per reply, context budget — enforced by Loremaster, not by the model. |
| **Obsidian-centric** | Package, paste, continue, and save all live in the plugin sidebar (and vault-watcher fallback). Phone and laptop share the same flow. |
| **Separate prompts** | Web partners use `AI/System/WebUI-Prompt.md` (evolved). They must **not** receive `vault:` command syntax meant for the local agent loop. |

---

## Roles

| Role | Who | Responsibility |
|------|-----|----------------|
| **User** | Human | Starts handoff, opens web UI, pastes replies, approves any future write proposals. |
| **Packager** | Loremaster service | Builds outbound package (prompt + context + tool catalog + schema). |
| **Partner** | Web model | Answers or emits `TOOL_REQUEST` blocks; never claims tool success without results. |
| **Executor** | Loremaster service | Parses partner reply, runs allowlisted tools, returns results for the next package. |
| **Plugin** | Obsidian (desktop + mobile) | UX: Ask web partner, Copy / Open, Paste response, Continue, Save. |

---

## Session model

Each handoff is a **web partner session**:

- `session_id` — opaque id (e.g. date + short slug)
- `partner` — `gemini` | `claude` | `chatgpt` | `grok` | `other`
- `private_opt_in` — bool (default false)
- `round` — increments on each Continue
- `research_dir` — `AI/Research/web-partner/YYYY-MM-DD-<slug>/`
- Transcript files (suggested):
  - `00-question.md` — original user question + metadata
  - `01-package.md`, `02-partner-reply.md`, `03-tool-results.md`, …
  - `final-answer.md` — when partner emits `FINAL_ANSWER`
  - `session.json` — machine state (optional; or pure Markdown)

Sessions are **resume-friendly** after app restart if state is in the vault.

---

## Tool allowlist (Phase 1)

Only these tools may be advertised to web partners and executed from `TOOL_REQUEST` blocks:

| Tool | Purpose | Notes |
|------|---------|--------|
| `vault:read` | Full text of a note | Path-jailed; respect private unless opt-in |
| `vault:search` | Full-text search | Same privacy filters as local search |
| `vault:list` | One-level folder listing | |
| `vault:find` | Recursive glob | |
| `vault:links` | Note + outgoing wikilinks | |
| `vault:ask` | Semantic Vault QA + citations | Local embeddings; no vault data leaves for indexing |
| `vault:query` | Structured/exact search | `tag:`, `path:`, `fm:`, phrase, NEAR |
| `vault:sources` | Provenance audit for a claim | |
| `vault:passage` | Bible passage guide from notes | |
| `vault:guide` | Knowledge-graph topic guide | |

### Explicitly forbidden (Phase 1)

- `vault:create`, `vault:update`, `vault:copy`, `vault:move`, `vault:trash`, `vault:mkdir`
- `vault:ingest`, `vault:ocr`, `vault:transcribe`, `vault:webresearch` (partner can use its own web)
- `command:run`, scripts, provider registry maintenance
- Any path outside the vault jail

**Later (M46+ Approvals bridge):** partner may *suggest* a write in plain language; Loremaster stages an Approvals item. The partner still never gets a write tool that applies immediately.

---

## Wire format (partner-facing)

Keep the format **plain text**, tolerant of messy model output. Prefer blocks over strict JSON (free web UIs often mangle JSON).

### Outbound package (what we send)

Structure produced by the packager (user copies this into the web UI):

```text
=== LOREMASTER WEB PARTNER PACKAGE ===
Session: <session_id>  Round: <n>  Partner: <name>
Private-opt-in: <yes|no>

## Instructions
<contents derived from WebUI-Prompt.md — protocol rules, honesty, how to emit blocks>

## Tool catalog
- vault:read <path> — Read the full text of a note.
- vault:search <query> — Full-text search across the vault.
- vault:list [folder] — List one level of the vault folder tree.
- vault:find <glob> — Recursive glob (e.g. 06 - Projects/**/*.md).
- vault:links <note> — Note plus notes it wikilinks to.
- vault:ask <question> — Semantic answer from the vault with citations.
- vault:query <expr> — Structured search (tag:/path:/fm:/"phrase"/NEAR).
- vault:sources <claim> — Which notes support a claim.
- vault:passage <ref> — Passage guide from Bible-related notes.
- vault:guide <topic> — Knowledge-graph guide for a topic.

When you need vault data, emit one or more TOOL_REQUEST blocks (see schema).
When you can answer fully, emit a single FINAL_ANSWER block.
Do not invent note contents, paths, quotes, or tool results.

## User question
<question>

## Context
### Active note (optional)
<title + truncated body>

### Attached notes (optional)
...

### Related titles only (optional)
- Note A
- Note B

## Prior tool results (rounds > 1)
...
=== END PACKAGE ===
```

### Partner reply schema

**Tool request** (one or more per reply):

```text
TOOL_REQUEST
name: vault:search
args: query="rocket stove design"
---
```

```text
TOOL_REQUEST
name: vault:read
args: path="06 - Projects/Rocket-Stove/Index.md"
---
```

**Final answer:**

```text
FINAL_ANSWER
... markdown body ...
```

### Parser rules (Loremaster)

1. Case-insensitive headers: `TOOL_REQUEST`, `FINAL_ANSWER`.
2. `name:` required; must match allowlist (with or without `vault:` prefix normalized).
3. `args:` free-form key="value" or key: value pairs; unknown keys ignored.
4. Blocks separated by `---` or blank line + new header.
5. If both tool requests and final answer appear, **run tools first** and ignore final answer for that round (model jumped ahead).
6. If neither appears, treat entire reply as a soft final answer and mark session `needs_user_confirm` (user can Save or Continue with a nudge).
7. Max **3** tool requests per partner reply; max **5** rounds per session (configurable).

### Tool result injection (next package)

```text
## Tool results (round n)
### vault:search query="..."
<status ok|error>
<output truncated to budget>

### vault:read path="..."
...
```

Errors are included verbatim (e.g. path not found, private blocked). The partner must not claim success on failed results.

---

## Privacy

| Situation | Behavior |
|-----------|----------|
| Sidebar **Private** on, no opt-in | **Ask web partner** disabled or shows hard warning; package build refused. |
| User enables **Allow private context for this handoff** | Package may include private active/attached notes; transcript folder tagged `private: true`; episode logged as web-handoff-private. |
| Tool hits a private note without opt-in | Executor returns a redacted error: `private note — not available to web partners`. |
| Connector / remote callers | Same rules; see Connector-Surface. |

Never put API keys, `settings.json` secrets, or full episode logs into a package.

---

## Context budget

Packager should:

- Prefer titles + short excerpts over full notes.
- Cap total package size (e.g. ~12–16k tokens equivalent; tunable).
- Use existing relevance ranking / related-notes where available.
- On Continue, include **only new** tool results plus a short rolling summary of prior rounds if needed — not the entire history every time.

---

## Plugin UX (sidebar)

1. **Ask web partner** menu — Gemini · Claude · ChatGPT · Grok · Other
2. Optional: **Include private context** (off by default)
3. **Copy package** · **Open partner** (platform URL where known)
4. **Paste response** — textarea; **Run tools / Continue**
5. Show tool results inline in the Loremaster chat thread
6. On `FINAL_ANSWER`: show answer · **Save to Research** · **Close session**
7. Badge/session chip: partner name + round + private flag

Mobile: same controls; no dependency on desktop webview. User switches to system browser and back.

### Vault-watcher parity

When the HTTP service is unreachable (typical phone-only edge case):

- User (or plugin) can write a pending request note with frontmatter that carries package intent / pasted partner reply.
- Box processes when online; writes tool results or final answer back into the vault via Sync.

Exact frontmatter keys to be defined at implementation time; must not break existing `assistant-status` / `assistant-request` flow.

---

## Service modules (suggested)

```
assistant_core/web_partner/
  __init__.py
  packager.py      # build outbound package from session + context
  parser.py        # TOOL_REQUEST / FINAL_ANSWER extraction
  executor.py      # allowlist check + tool dispatch (reuse tool registry)
  session.py       # session_id, round, research_dir, persistence
  loop.py          # orchestrate parse → execute → next package / final
```

Reuse path jail, privacy flags, and tool implementations from existing vault tools. Do **not** route web-partner tool execution through the full local agent loop with write tools enabled.

---

## Updates to existing artifacts

| Artifact | Change |
|----------|--------|
| `AI/System/WebUI-Prompt.md` | Replace “you have no tools” with protocol: emit `TOOL_REQUEST` / `FINAL_ANSWER`; honesty rules; no fabricated vault content. |
| `Docs/System-Prompt.md` / seeded system prompt | Document web partner path for the *local* model (when to recommend Ask web partner vs local tools). |
| `AI/Help/Commands.md` / Features | User-facing: how to run a web partner session. |
| Episode helpers | `ep_handoff` with sent / tool / returned / final and session_id. |

---

## Testing (M43–M45)

- Parser golden cases: clean blocks, missing separators, extra commentary, JSON-ish mistakes, both FINAL and TOOL in one reply.
- Allowlist rejection: create/update/move requests → error, no side effects.
- Privacy: private note without opt-in → blocked tool result.
- Cap: 4th tool in one reply ignored or error; 6th round refused.
- Packager budget: large active note truncated deterministically.
- Plugin: copy/paste/continue round-trip on desktop and mobile viewport.
- Watcher fallback: one offline paste → online process → result in vault.

---

## Non-goals (this document)

- Browser DOM automation or extension injection (optional later; not required for Path 1).
- Giving web partners direct write access to the vault.
- Merging WebUI-Prompt with the local System-Prompt.
- Replacing free-tier **API** routing in `Provider-Registry.md` (that remains separate).

---

## Open decisions

1. Exact max package size and per-result truncation limits.
2. Whether soft final answers (no block headers) auto-save or require explicit Save.
3. Partner-specific packager presets (Claude vs Gemini tone/structure) — file: `AI/System/Web-Partners.md`.
4. Frontmatter schema for watcher-mediated partner rounds.

---

## Milestone mapping

| Milestone | Deliverable |
|-----------|-------------|
| **M43** | This protocol implemented in service: packager, parser, executor, session; CLI/test harness. |
| **M44** | Sidebar Ask web partner + paste + tool run + continue. |
| **M45** | Multi-round UX, research save, privacy gates, watcher parity. |

See also: [`Connector-Surface.md`](Connector-Surface.md) for exposing the **same allowlist** as MCP/HTTP connectors (Path 2).
