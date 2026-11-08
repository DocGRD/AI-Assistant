```markdown
# Plan: Teach Loremaster to use Obsidian (and its plugins) like Cursor / Claude learn an IDE

**Status:** Vision + near-term roadmap  
**Context:** M41 already gives Loremaster the full command palette (`command:search` / `list` / `run` with approve-to-execute). This plan goes further so Loremaster can *operate* Obsidian the way Cursor agents operate VS Code or Claude Cowork operates a desktop.

---

## Analogy

| Cursor / Claude Code | Loremaster target |
|----------------------|-------------------|
| File tools + terminal + browser | Vault tools + Obsidian commands + workspace actions |
| Learns project structure from repo | Learns vault structure + active layout + installed plugins |
| Approves destructive shell | Approves every consequential Obsidian action |
| Skills / rules files | `AI/Help` + system prompt + learned facts about *this* vault’s plugins |

We do **not** need pixel-level computer-use for the core path. Obsidian already exposes a rich internal API. We should use that first, and only consider screen-level control as a last resort.

---

## What already exists (M41)

- Plugin pushes the entire command palette (core + every community plugin) to the service.
- Agent can `command:search`, `command:list`, `command:run <id>`.
- Execution is always propose → user Approve → plugin runs `executeCommandById` in the renderer.
- Destructive / outward-facing commands are flagged.

This is the right foundation. Gaps:

1. Agent still under-uses the palette (self-model / prompt coverage).
2. Commands are only half of Obsidian; workspace, leaves, views, metadata, and plugin-specific surfaces are not yet first-class tools.
3. No durable “how this vault is set up” memory (which plugins, preferred workflows, hotkeys, templates).

---

## Target capability layers

### Layer 1 — Command mastery (near-term, low risk)

- Strengthen system prompt + `AI/Help` so the agent *defaults* to `command:search` when the user asks for something a plugin can do (“insert daily note template”, “open calendar”, “start Kanban”).
- After each successful `command:run`, optionally record a short learned fact: “User uses Templater template X for daily notes.”
- Add `command:help <id>` if we can surface any description (manifest / custom map).

### Layer 2 — Workspace & view tools (medium)

New plugin-executed, approve-gated actions (same proposal UX as `command:run`):

| Action | Purpose |
|--------|---------|
| `workspace:active` | What file / mode / leaf is focused |
| `workspace:open <path>` | Open note in current / new leaf |
| `workspace:split` | Split, move leaf, focus sidebar |
| `workspace:set-mode source\|preview` | Switch edit vs reading view |
| `editor:get-selection` / `editor:replace-selection` | Structured edit without full propose/commit path when appropriate |
| `workspace:list-leaves` | See open tabs / sidebars |

All of these run only in the plugin (renderer), never on the Python service.

### Layer 3 — Plugin-aware skills (medium → longer)

- On load / on plugin enable, capture a compact catalog: plugin id, name, manifest description, command ids.
- Store under `AI/System/Obsidian-Plugins.md` (or per-device state + a vault summary).
- Let the agent ask “what can Templater / Dataview / Calendar do here?” and get grounded answers from that catalog + help notes.
- Optional: user-authored “skill” notes (`AI/Skills/templater-daily.md`) that teach preferred workflows; agent is instructed to read them before acting.

### Layer 4 — Deeper internal API (careful)

Using documented + carefully guarded internal surfaces:

- Metadata cache queries beyond current vault tools.
- Graph view focus / local graph.
- File explorer reveal.
- Specific well-known plugin APIs only when stable and optional.

Always: feature-detect at runtime, degrade gracefully, never crash the plugin.

### Layer 5 — Optional computer-use fallback (long / optional)

Only if Layers 1–4 cannot express a needed action. High risk, high maintenance; keep behind an explicit setting and heavy confirmation. Not required for “learn Obsidian.”

---

## Design rules (non-negotiable)

1. **Propose / approve for anything consequential** — same discipline as vault edits and `command:run`.
2. **Plugin executes, service plans** — Obsidian APIs only run in the renderer.
3. **Self-model honesty** — system prompt must state what the *system* can do (commands, workspace, speak) so the agent stops denying real capabilities.
4. **Learn this vault** — successful actions and user corrections become durable facts / skill notes.
5. **Zero-cost path remains default** — no new paid APIs required for core control.

---

## Suggested milestone split

| Milestone | Scope |
|-----------|--------|
| **M-Speak** | TTS quality + `[[SPEAK]]` (separate PR) |
| **M-Cmd-Fluency** | Prompt + help so agent reliably uses existing command palette |
| **M-Workspace** | `workspace:*` / `editor:*` proposal actions |
| **M-Plugin-Skills** | Auto catalog + optional user skill notes |
| **M-Deep-API** | Selective internal APIs with runtime guards |

---

## Success look-like

User: “Open today’s daily note, switch it to reading view, and read the Morning section aloud.”

Loremaster:

1. `command:search daily note` → `command:run …` (approve)
2. `workspace:set-mode preview` (approve or auto if marked safe)
3. `[[SPEAK: … | section: "Morning"]]`

…and afterwards remembers the preferred daily-note command for this vault.

That is the Cursor/Claude-level loop, implemented on Obsidian’s own APIs instead of screen scraping.
