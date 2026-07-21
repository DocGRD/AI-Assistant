<!-- help-version: 40 -->
---
tags: [help, user-guide]
---
# Features — by task

Part of [[How-To-Use]]. See [[Commands]] for the exact syntax.

## Read the Bible (study reader)

The public-domain **World English Bible (WEB)** ships as notes under `bible/`, one folder per book in
canonical order (`bible/40-matthew/…`), one note per chapter (`bible/40-matthew/web/matthew-001.md`).
Open one in **Reading view** (chapters auto-open there) and you get:

- **Cross-references** as small superscript markers after each verse. Hover a marker to see the
  reference and the full linked verse; click it to open that verse (Ctrl/Cmd-click opens a new tab).
  The read-card has a **×** close button and closes when you tap away. The references are stored once
  in `AI/bible-crossrefs/` and drawn on by the plugin, so they are the same for every translation.
- **Tap the verse number → a study popup** for that verse: at the top, a **📖 Matthew Henry** link to
  the chapter's commentary and links to **your own** commentary notes on that verse; below, *all* of
  the verse's cross-references and related-by-meaning links. Available on every verse. × to close, or
  tap away.
- **Matthew Henry's Commentary** — a **📖 Matthew Henry on <Book> <Ch>** link sits under each chapter's
  title, and is also in the verse-number popup, so you can reach the commentary from anywhere you read.
- **Pin a cross-reference to a word.** In the verse-number popup, each cross-reference has an **⚓**
  button: click it, then click the word it relates to, and its marker moves to sit right after that
  word instead of clustering at the end. A pinned marker shows even when you've toggled the general
  cross-references off — so you can keep a clean page and surface just the links that matter, next to
  the words they explain. (Stored in the note's `bible-xref-anchors`; "Move back to the end of the
  verse" undoes it.)
- **Verse-by-verse or flowing paragraphs** — run the command *"Bible: toggle reading layout"*.
- **Poetry** (Psalms, Proverbs) laid out as indented poetry; **prose** grouped into paragraphs.
- **Red-letter** — the words of Christ (Gospels, Acts, Revelation) render in red.
- **"Related by meaning"** — a distinct section per chapter with embedding-similar passages, plus a
  per-verse `≈` marker; both deduplicated against the cross-references.
- **Text size** — Settings → Loremaster → Bible reader → **Text size** (80–160%), reader-only.
- **On mobile**, tap a superscript marker to open its read-card (with **Open**) rather than jumping away.

### Annotate: highlight, words of Christ, tag a Strong's number

You can mark up any translation yourself — this is how you add red-letter or Strong's to a version that
doesn't ship with them. Open the chapter in **edit mode**, select the word(s), then run one of these
(Command Palette, or right-click → the **Bible** menu):

- **"Bible: highlight selection"** — wraps it in `==…==` (a highlight).
- **"Bible: mark selection as words of Christ (red)"** — renders the selection red, like the built-in
  red-letter. Use this to mark Christ's words in ESV/NASB/NKJV or anywhere they aren't already red.
- **"Bible: tag selection with a Strong's number"** — asks for a number (e.g. `H430`, `G26`) and tags
  the word, so the Strong's hover/tap popup then works on it in **any** translation.

Switch back to Reading view to see the result. (These edit the note text, so they need an active editor
and a selection — they won't appear when the note is in Reading view.)

### Interlinear & concordance (Strong's)

- **Interlinear** — command *"Bible: interlinear (this chapter)"* opens the open chapter word-by-word,
  each word tagged with its **Strong's number**. Tap a number for its Hebrew/Greek word,
  transliteration, meaning, and a link into the concordance.
- **Concordance** — command *"Bible: concordance (Strong's number or word)"*. Enter a Strong's number
  (`H430`, `G26`) or an English word (`love`) and get every verse that uses it, each a link.
- Accuracy note: the WEB's own word-tags are unreliable, so the Strong's data is built from the
  public-domain **KJV + Strong's** (the basis of Strong's Concordance) plus the openscriptures
  lexicon. It lives in `AI/bible-strongs/`; the WEB stays your reading text.

### Your own commentary

Write your own notes on scripture and see them in the reader. Command *"Bible: write a note on this
verse"* (from an open chapter) creates a note under `bible-commentary/` carrying `commentary-ref:
<book>.<ch>.<v>` (a single verse, a range `…v-v2`, or a whole chapter `<book>.<ch>`). Verses you've
written on get a **✎** marker right after the verse number (tap to open your note); your notes are
also listed at the top of that verse's number popup and under the chapter. Write freely — it's your
growing study library. *(A hand-made commentary note only links to its verse if it carries a
`commentary-ref:` line in its frontmatter — the "write a note" command adds this for you.)*

You can also attach a note to **specific words**: select a word or phrase in a chapter and run
*"Bible: attach a note to selection"* (or right-click → Bible). A **📝** appears at the front of those
words in the reader and opens the note when tapped — and because the note carries `commentary-ref`, it
shows in the verse's ✎ list too.

### Quote a passage into a note

To drop scripture into a study note, sermon outline, or journal entry, run **"Bible: insert a passage
(into this note)"** from the editor. Pick the book, chapter, a verse range (`1-5`, `1,3,5`, or a single
`3`), and version — LoreMaster inserts a small `bible-passage` block that renders as **one flowing
paragraph** (inline superscript verse numbers, red-letter, the reader's look), read **live** from the
chapter note: it *displays* the text rather than copying it, so if the source verse changes the passage
updates. A reference link back to the chapter sits below it.

### Get a chapter from a licensed online version (ESV / NASB / NKJV)

The fastest way to add another translation: run the command **"Bible: get a chapter (ESV / NASB / NKJV)"**,
pick the version, book slug and chapter. LoreMaster fetches it through your local service (your API keys
stay on the service — set them under *Privacy & Settings → Bible version keys*), **saves it in the vault**,
and opens it — so it's only ever fetched once and gets the full reader treatment. ESV automatically honours
its 500-verse caching cap.

### Add a chapter from another translation (by hand / paste)

The WEB is included; you can add a chapter of any translation **you have legal access to** by pasting
it into a note in the standard format (the cross-references then appear automatically — you never add
them by hand). Create the note at:

```
bible/{NN}-{book-slug}/{version}/{book-slug}-{CCC}.md
```

e.g. `bible/43-john/esv/john-003.md` for ESV John 3 (NN = book number 01–66, CCC = zero-padded
chapter). Give it this frontmatter and body:

```markdown
---
cssclasses:
  - bible
bible-version: esv
bible-book: john
bible-booknum: 43
bible-chapter: 3
bible-parastarts: 1,16,22
---
# John 3

**1** Now there was a man of the Pharisees named Nicodemus… ^v1
**2** This man came to Jesus by night… ^v2
```

Rules: each verse is `**{number}** {text} ^v{number}` (the `^v#` anchor is what cross-references land
on); `bible-parastarts` lists the verses that begin a new paragraph. **For poetry** (e.g. a Psalm), put
each poetic line (stich) on its own line, then select them and run *"Bible: format selection as poetry"*
— it adds the hard breaks and em-space indents the reader renders as poetry, so you don't type them by
hand. **Copyright:** only add translations you're licensed to store (WEB is public domain;
ESV/NASB/NKJV are copyrighted — use them only within their terms). Prefer the command
*"Bible: paste a chapter (new translation)"* — paste the raw text and LoreMaster splits it into the
standard verse format for you. For a Psalm or other poetry, turn on the **Poetry** toggle in that dialog
and the line breaks in what you paste are kept as poetic lines (indented stichs).

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