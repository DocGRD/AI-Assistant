<!-- help-version: 25 -->
---
tags: [help, user-guide]
---
# Features — by task

Part of [[How-To-Use]]. See [[Commands]] for the exact syntax.

## What's new in v1.6 (quick map)
- **📥 Approvals inbox** (sidebar badge-button → modal) — every background proposal in one place:
  auto-organize tags/links/**folder**/**project**, memory facts, goal approvals. Apply/dismiss **per item**;
  Loremaster **learns** from your choices.
- **🎯 Goals** (badge-button → modal) — running goals with progress + Pause/Resume/Cancel. Plan with
  `vault:goal`, use `--template research|digest|study`, `--recurring`, `--budget`.
- **Inline editing** — editor commands **Continue writing / Rewrite selection / Compose** open a preview
  popup (Accept / Regenerate / Cancel); private routing.
- **Trust on write** — created/edited notes flag unsourced factual claims; `vault:contradictions` finds
  conflicts.
- **Vault intelligence** — `vault:analytics` (orphans/stale/unsourced/hubs/tag-merges), `vault:moc`,
  `vault:actions`.
- **Capture** — `vault:clip <url>` saves web pages **and YouTube transcripts**; `vault:template` fills your
  Templater templates.

## Using your Obsidian plugins (v1.10)
Loremaster is aware of your **whole Obsidian command palette** — core commands and the commands from every
community plugin you install — so it can actually *drive your plugins* for you.
- **Just ask in plain language:** "insert my daily-note template", "open the calendar", "create a new
  Excalidraw drawing", "start a Kanban board". Loremaster searches the palette, picks the matching command,
  and shows a one-click **Approve & run** card. It (not the service) runs the command inside Obsidian.
- **Safe by default:** every command is approved before it runs, and destructive or outward-facing ones
  (delete, publish, sync) are flagged with a ⚠.
- **Zero setup for new plugins:** install or enable a plugin and its commands are immediately available to
  Loremaster. It re-syncs on load, when the workspace changes, and via the **Refresh Obsidian commands**
  palette command. (Power users: `command:search <query>` and `command:run <id>` do this explicitly.)

## Chatting & context
Type in the sidebar and **Send**. To steer what the assistant looks at:
- **Active note** — the note you have open is given as context automatically.
- **+ Note / `@`** — pick specific notes to pull in as context (mention chips).
- **+ Selection** — attach the text you've selected in a note.
- **📎 (paperclip)** — attach a vault file: a document (PDF/EPUB/Word/text) is **ingested** into
  `AI/Library` and indexed; an image is **analysed** (its text transcribed + described). (Copy an external
  file into the vault first — Obsidian drag-and-drop works.)
- **Related notes ▾** (Add context) — a dropdown of notes semantically related to the active note; click
  any number of them to add each to the conversation's context (reopen to add more).
- **Actions ▾** (next to **Send**) — a menu holding **Vault QA** (toggle), **Summarize / Key points /
  Action items**, the **Fix grammar / Improve** quick edits, saved **Prompts…** from `AI/Prompts/`, and the
  **Graph** viewer.

> **Sidebar layout:** the **provider dropdown** and the **🔒 Private** toggle sit on the top line beside
> the **AI Assistant** title and the **⚙** settings gear. Everything else (Vault QA + quick actions) lives
> in the **Actions ▾** menu on the Send line.

## Editing notes (propose → commit) §Editing
The assistant never overwrites a note on its own. To edit:
1. Select text in a note → **+ Selection** (or just select and pick **Actions ▾ → Fix grammar / Improve**).
2. Turn on **✎ Edit** (not needed if you used an Actions edit).
3. Send an instruction ("fix grammar", "tighten this", "rewrite as bullets").
4. You get a **proposal** showing the **original → proposed** text rendered *the way Obsidian shows it*
   (headings, bold, lists — not raw code). Click **Replace** to apply exactly that range, **Keep editing**
   to refine, **Cancel** to discard it, or pick a word-option chip. If you changed the region first,
   Replace refuses ("the note changed — re-select"). Whole-note edits replace the body in one click.

## Search & Vault QA §Search
- **Keyword:** `vault:search <words>` — literal full-text (exact phrase, then all-words). Good for finding
  a note fast. Scope it with the `search_exclude_folders` / `search_include_folders` settings.
- **Semantic (Vault QA):** turn on **📚 Vault QA** (or `vault:ask <question>`) — answers from across the
  whole vault using the local index, with **cited source chips**. Blends meaning + your `[[links]]` and
  `#tags`. Scope it to a folder/tag with the QA scope control ("project mode").

## Research — two ways §Research
- **Autonomous (web):** `vault:webresearch <question>` — searches the web, fetches the top pages, writes a
  **cited** synthesis plus the verbatim sources under `AI/Research/<date>-<slug>/`, and links real related
  notes. Free by default (keyless DuckDuckGo); add a key for Brave/Serper/Tavily/Exa/Google. **Never runs
  on a private turn.**
- **Manual round-trip:** `vault:research <question>` gives you a prompt to paste into your own web AI
  (ChatGPT/Gemini/Claude). Paste the answer back (**Submit response** in the plugin, or `---end` in the
  terminal) → it saves the research verbatim, adds a short summary, and links real related notes.

## Documents §Documents
`vault:ingest <path/to/file>` extracts a **PDF, EPUB, Word (.docx), or text** file into a searchable
`AI/Library/<slug>.md` note (with `## Page N` provenance anchors), so it answers in Vault QA. The original
file is untouched. Install the matching library once (`pip install pypdf ebooklib python-docx`); `.txt`/
`.md` need nothing.

## Images & handwriting §Images
`vault:ocr <note>` reads the text out of images embedded in a note (`![[scan.png]]`) — using a free
multimodal model, or local `tesseract` offline — and saves it to an additive `AI/Derived/<note>.ocr.md`
sidecar that Vault QA can then answer from. **Excalidraw** drawings are searchable automatically (their
typed text is indexed). Private notes' images stay on no-train models or local OCR.

## Knowledge graph & guides §Graph
Build it with `vault:graph <note>` (one note) or `python -m assistant_core --build-graph` (whole vault,
incremental). Entities and relations become linked notes under `AI/Graph/Entities/` — browse them in
Obsidian's graph view or the plugin's **Graph** button (click **Browse all** to explore without knowing
names). `vault:guide <topic>` assembles a **cited** overview of an entity and everything connected to it.
`vault:graph-merge A -> B` merges duplicates. Whether private entities appear is the
`graph_include_private` setting.

## Memory & automation
The assistant remembers across sessions (user profile, learned facts, per-project notes, daily episode
logs). Say `remember: <fact>` to save one. Nightly it "dreams" — turning episodes into **proposed** durable
facts you review in the plugin's **🧠 Memory review** panel — and archives old episodes. See
[[Privacy-and-Settings]] for the schedule and toggles.