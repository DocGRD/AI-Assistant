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
| `vault:ingest <file>` | Extract a PDF/EPUB/DOCX/txt into a searchable `AI/Library/` note |
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

## Providers, index & ops (admin)
| Command | What it does |
|---|---|
| `vault:models` | List models your keys actually unlock |
| `vault:discover-providers` | Build a proposed registry from each provider's live `/models` |
| `vault:update-providers [apply]` | Refresh the provider registry (propose, then apply) |
| `vault:reindex [full]` | Rebuild the Vault QA index (box only) |
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
