<!-- help-version: 31 -->
---
tags: [help, user-guide, commands]
---
# Command Reference

Part of [[How-To-Use]]. Type these in the **plugin chat** or the **terminal**. Put the path on the first
line for `create`/`update`; use `-> ` between two paths for copy/move.

## Read & find
| Command | What it does |
|---|---|
| `vault:read <note>` | Show a note's full text (path or just the name) |
| `vault:search <words>` | Full-text search; exact phrase, else all-words; logs/episodes excluded |
| `vault:list [folder]` | List one folder level |
| `vault:find <glob>` | List every note matching a glob, e.g. `06 - Projects/**/*.md` |
| `vault:query <expr>` | **Structured/exact search** — `tag:x` `path:"…"` `fm:key=value` `"phrase"` `A NEAR/3 B` |
| `vault:links <note>` | A note plus everything it wikilinks to |
| `vault:ask <question>` | **Vault QA** — semantic answer across the whole vault, with cited sources |

## Write & restructure
| Command | What it does |
|---|---|
| `vault:create <path>` ⏎ `<content>` | Create a new note |
| `vault:update <path>` ⏎ `<content>` | Append to a note |
| `vault:copy <src> -> <dst>` | Copy a note or a whole folder |
| `vault:move <src> -> <dst>` | Move / rename |
| `vault:trash <path>` | Move to `.trash/` (recoverable — never hard-deleted) |
| `vault:mkdir <path>` | Create a folder |

## Research & knowledge
| Command | What it does |
|---|---|
| `vault:research <question>` | Generate a prompt for a web AI; paste the answer back (manual round-trip) |
| `vault:webresearch <question>` | **Autonomous** web search + fetch + cited synthesis → `AI/Research/` |
| `vault:summarise <note>` (or `summarize`) | Load a research note and summarise it |
| `vault:ingest <file>` | Extract a PDF/EPUB/DOCX/txt/HTML into a searchable `AI/Library/` note. A **`.zip` of HTML** files (or a folder of them) imports as an interlinked **collection** — every file becomes a note and inter-file links are rewritten to vault wikilinks |
| `vault:analyze <image>` | Transcribe + describe one image (the 📎 paperclip uses this) |
| `vault:ocr <note>` | Read text from a note's images/handwriting → `AI/Derived/` sidecar |
| `vault:graph <note>` | Extract entities/relations from a note into the knowledge graph |
| `vault:guide <topic>` | Assemble a cited overview of a topic from the graph + notes |
| `vault:sources <claim>` | **Provenance audit** — which notes support a statement; flags unsourced claims |
| `vault:graph-merge <canonical> -> <alias>` | Merge two graph entities |
| `vault:passage <ref>` | Cited overview of a Bible passage (e.g. `1 John 2:18-20`) from your notes |
| `vault:transcribe <audio>` | Transcribe an audio file locally → `AI/Derived/` sidecar (searchable) |
| `vault:cards <note>` | Generate spaced-repetition flashcards from a note |
| `vault:review` | Show the flashcards due for review today |

## Proactive, trust & goals
| Command | What it does |
|---|---|
| `vault:briefing` | Write today's **Daily Briefing** (focus, changes, due cards, pending approvals, vault health) |
| `vault:consolidate` | Run **memory consolidation ("dreaming")** on demand → extracts durable facts from recent activity into **propose-only** memory items in the **📥 Approvals** inbox (nothing saved to Learned-Facts until you approve). Also runs nightly. |
| `vault:organize [note]` | Stage **propose-only** tag / related-link / folder / project suggestions. **With a note** (or the note you have open) → suggestions for **that** note, using your existing tags + validated links → staged in the **📥 Approvals** inbox. Bare → scans recently-changed notes. **Each related link comes with a grounded *reason*** (why it relates) shown in the panel; approving writes the links + reasons as a `\| Links \| Reason \|` table under `## Related` |
| `vault:analytics` | Read-only **"explain my vault"** report → `AI/Reports/` (orphans, stale, unsourced, hubs, tag-merges) |
| `vault:contradictions` | Flag notes that disagree on a number/date or via negation (deterministic) |
| `vault:moc <topic>` | Propose a **Map-of-Content** index note for a topic → `AI/Proposed/` |
| `vault:actions <note>` | Extract a note's to-dos into a tracked `AI/Tasks/` checklist (propose-only) |
| `vault:goal <description>` | Plan a background **goal**; approve it to run step-by-step. Flags: `--template research\|digest\|study`, `--recurring daily\|weekly\|monthly`, `--budget <calls/day>` |
| `vault:goal approve\|pause\|resume\|cancel <slug>` | Control a goal |
| `vault:goal replan <slug> :: <feedback>` | **Refine a proposed plan** — iterate until it's solid, then approve. (You can also just edit the `- [ ]` steps in the plan note; approve honors your edits.) |
| `vault:goals` | List all goals + progress |

*Auto-organize, memory-consolidation and goal approvals all collect in the **📥 Approvals** inbox
(badge-button → **dockable side panel**); apply/dismiss per item, or approve / **re-plan** / reject a goal.
Running goals live under the **🎯 Goals** button.*

## Authoring & capture
| Command | What it does |
|---|---|
| `vault:clip <url>` | Save a web page's readable text — or a **YouTube** transcript — as a sourced, indexed note in `AI/Clippings/` (disabled in Private mode) |
| `vault:template <name> [:: context]` | Fill a **Templater/Templates** template's fields from context → propose-only note |

## Obsidian command palette (core + your plugins)
Loremaster knows your whole Obsidian command palette — core **and every community plugin you install** — so
you can ask it to *use your plugins* ("insert my daily-note template", "open the calendar", "start a Kanban
board"). It finds the matching command and **proposes** running it; you approve with one click and the plugin
runs it. New plugins are picked up automatically (or force a re-sync from the palette).

| Command | What it does |
|---|---|
| `command:search <query>` | Find matching palette commands (returns each command's name + `id`) |
| `command:list [plugin]` | Browse the whole palette, or one plugin's commands |
| `command:run <id>` | **Propose** running a command → one-click **Approve & run** (destructive ones are flagged; nothing runs until you approve). The plugin executes it — the service can't |

*You usually don't type these — just ask in plain language ("use Templater to insert my daily note") and
Loremaster searches, then proposes the right command. The palette syncs on load, when you install/enable a
plugin, and via the **Refresh Obsidian commands** command.*

*Inline editing (editor commands, hotkeyable): **Continue writing**, **Rewrite selection**, **Compose with
Loremaster…** open a popup that previews the result before it's inserted (private routing — your note text
never goes to the web).*

*Read-aloud (editor commands): **Read note aloud** (reads a selection if you've highlighted text, else the
whole note) and **Stop reading**. A floating control bar gives Play/Pause/Stop, prev/next sentence, **speed**
(0.75×–2×), and a **voice** picker; the spoken sentence is highlighted as it reads. Every chat reply also has
a **🔊** button. Fully offline/on-device/private.*

*Reviewing background work: the **📥 Approvals** and **🎯 Goals** buttons (count badges) open a dockable
**side panel** — apply/dismiss per item, or pause/resume/cancel goals — without covering your notes.
`vault:sync-help` refreshes these help notes.*

## Providers, index & ops (admin)
| Command | What it does |
|---|---|
| `vault:models` | List models your keys actually unlock |
| `vault:discover-providers` | Build a proposed registry from each provider's live `/models` |
| `vault:update-providers [apply]` | Refresh the provider registry (propose, then apply) |
| `vault:reindex [full]` | Rebuild the Vault QA index (incremental; `full` = clean rebuild) |
| `vault:logs [N\|errors\|today]` | **Read Loremaster's own logs** (`logs/assistant.log`, outside the vault) for self-diagnosis — last N lines, recent `errors`, or `today` |
| `vault:test` | Run the automated test suite |
| `vault:run-script <name>` | Run an **approved** script from `AI/Scripts/` |

## One-shot subcommands (terminal)
```bash
python -m assistant_core --consolidate [--apply]     # nightly "dreaming": episodes → durable facts
python -m assistant_core --build-graph [--limit N]   # incremental knowledge-graph build
```

**Notes.** Use hyphens in new note names (not spaces/slashes). Restructuring (`copy`/`move`/`trash`/
`mkdir`) is **propose-and-approve**: ask the assistant in plain language to move, rename, remove, or file
notes and it stages the change as a one-click **Approve / Reject** card — nothing happens until you
approve (and `trash` moves to `.trash/`, recoverable). `ingest`, `ocr`, `graph`, and `discover-providers`
stay **user-only** — the assistant won't run them on its own. See [[Privacy-and-Settings]] for what's
blocked when a turn is private.