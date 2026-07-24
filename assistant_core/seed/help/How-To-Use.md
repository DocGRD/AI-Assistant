<!-- help-version: 58 -->
---
tags: [help, user-guide]
---
# How to Use LoreMaster

*The complete map of what LoreMaster can do. These `AI/Help/` notes are **indexed**, so you can also just
ask "how do I …?" in chat and LoreMaster answers from them. (Run `vault:sync-help` to refresh them.)*

LoreMaster is a zero-cost, local-first AI brain for this vault. It reads and writes your notes, keeps its
memory as plain Markdown, works proactively in the background, and routes every request across **free-tier**
providers only. Notes you mark private never leave your machine.

**Two golden rules:** it only claims it did something when a real tool result backs it up, and it **never
overwrites a note on its own** — edits, moves, provider changes and background suggestions are always
**proposed for you to approve**.

## The other guides
- [[Getting-Started]] — install, run the service, connect the plugin, first chat, phone setup.
- [[Commands]] — exact syntax for every `vault:` command.
- [[Features]] — task-by-task walkthroughs with detail.
- [[Privacy-and-Settings]] — the 🔒 Private toggle, providers, settings, nightly automation.
- [[Whats-New]] — newest capabilities, newest first.
- [[User-Guide]] — the long-form end-to-end guide.

---

## 1. Chat

| I want to… | Do this |
|---|---|
| Chat | Open the **LoreMaster** sidebar, type, **Send** |
| Give it a note as context | **+ Note** (picker) or **+ Selection** (highlighted text) |
| Attach a file | 📎 paperclip (PDF, EPUB, Word, image, audio…) |
| Keep this exchange local-only | Toggle **🔒 Private** (or put `private: true` in the note) |
| Choose how it routes | The model dropdown — **Auto (smart routing)** picks a free provider per task |
| Clear the thread | **Clear** |
| Compose a longer piece | Command **Compose with LoreMaster…** |
| Re-run a saved prompt | Command **Run a saved prompt** |

## 2. Ask your vault (RAG)

| I want to… | Do this |
|---|---|
| Ask across the whole vault, with citations | **Actions ▾ → Vault QA**, or `vault:ask <question>` |
| Keyword-find a note | `vault:search <words>` / `vault:find <name>` |
| Structured query | `vault:query <expression>` |
| Summarise a note | Command **Summarize active note**, or `vault:summarise <note>` |
| Read / list / create notes | `vault:read`, `vault:list`, `vault:create`, `vault:mkdir` |
| Re-index after bulk changes | `vault:reindex` |

## 3. Write and edit notes

Edits are **proposed, then approved** — you always see a diff first.

| I want to… | Do this |
|---|---|
| Rewrite selected text in place | Select → **Rewrite selection (inline)** → preview → **Accept** |
| Continue writing from the cursor | **Continue writing (inline)** |
| Edit a note by asking | Select text → **Actions ▾ → edit**, or just ask → **Approve** the diff |
| Reorganise / move / rename / delete | Ask in plain language → **Approve** the change card |
| Bulk tidy | `vault:organize`, `vault:update`, `vault:copy`, `vault:move`, `vault:trash` |
| Fill one of your templates | `vault:template <name> :: <context>`, or **Fill a template with LoreMaster** |

## 4. Research and capture

| I want to… | Do this |
|---|---|
| Research a question on the web | `vault:webresearch <question>` (auto-searches, reads, cites) |
| Research inside the vault | `vault:research <topic>` |
| Save a web page or YouTube video | `vault:clip <url>`, or **Clip a web page to the vault** |
| Check where a claim came from | `vault:sources` |

## 5. Documents, images, audio

| I want to… | Do this |
|---|---|
| Bring in a PDF / EPUB / Word / HTML archive | 📎 paperclip, or `vault:ingest <file>` |
| Read text out of an image or handwriting | 📎 an image, or `vault:ocr <note>` |
| Transcribe audio / video | `vault:transcribe <file>` |
| Read a note aloud | **Read note aloud** (or 🔊 on a chat reply) → floating bar with **speed** + **voice**; **Stop reading** to end. Speech is generated on the service, so it works on Android too |

## 6. Understand your vault

| I want to… | Do this |
|---|---|
| See how notes connect | **Graph** button, or `vault:graph <note>` |
| Everything on a topic | `vault:guide <topic>` or `vault:moc <topic>` (Map of Content) |
| Health check | `vault:analytics` (orphans, stale notes, hubs, tag merges) |
| Find notes that disagree | `vault:contradictions` |
| Merge duplicate graph entities | `vault:graph-merge` |
| Pull the to-dos out of a note | `vault:actions <note>` |
| Fold scattered notes together | `vault:consolidate` |
| See link structure | `vault:links` |

## 7. Memory, proactivity and goals

LoreMaster keeps its own memory as Markdown and works while you're away.

| I want to… | Do this |
|---|---|
| Review what it suggested | **📥 Approvals** (badge = count) → apply or dismiss per item |
| Read today's digest | **🗞️ Briefing**, or `vault:briefing` |
| See running goals | **🎯 Goals** → pause / resume / cancel, or `vault:goals` |
| Start an autonomous goal | `vault:goal <description>` — options `--template research\|digest\|study`, `--recurring`, `--budget` → then approve it |
| Review its recent work | `vault:review` |
| Spaced-repetition cards | `vault:cards` |

## 8. The Bible study suite

A full local study Bible. The public-domain **WEB** ships as the reading text; **KJV** and **BSB** ship
Strong's-tagged; you can paste any translation you're licensed to use.

**Reading**
- Chapters live in `bible/`, open in Reading view, and stay in edit mode once you switch.
- **Cross-references** as superscript markers (hover to preview, click to jump); several on one word
  collapse to a single letter that opens a list.
- **Related by meaning** (`≈`) from the verse-embedding index.
- **Tap the verse number** → study popup: your commentary, 📖 Matthew Henry, all cross-references and
  related passages, textual-variant notes (`†`).
- **Version switcher** (top-right) and **Bible: toggle reading layout** (verse-by-verse ⟷ flowing).
- Poetry renders with a hanging indent; **red-letter** words of Christ; adjustable **text size**.

**Original languages**
- **Interlinear** (*Bible: interlinear (this chapter)*) with a **Text** switch: KJV/Strong's, **SBLGNT**
  (Greek NT), **WLC** (Hebrew OT, right-to-left), **English ⟶ original order (BSB)**, and — once aligned —
  your own pasted version in original word order.
- **Concordance** (*Bible: concordance*) — every verse using a Strong's number or English word.
- **Morphology search** (*Bible: morphology search*) — "aorist active", "genitive plural"…
- **Lexicon** — Strong's plus fuller **Dodson** (Greek) / **BDB** (Hebrew) definitions on hover.

**Connect any translation to the originals (approximation engine)**
- *Bible: align this version to the original (approximate)* — or it runs automatically after you paste a
  chapter. It guesses each word's Strong's by comparing your text to the tagged BSB, unfoldingWord ULT and
  KJV, entirely offline.
- Several English words that render **one** original word are linked **as a phrase** ("he gave" → δίδωμι);
  English words supplied for clarity get no link at all.
- Guesses show a dotted amber underline — tap one to **Confirm**, **Change…** or **Not a match**.
  *Bible: review Strong's guesses* walks the uncertain ones, least confident first.
- **Connect a word yourself** — select the English and choose *"Connect … to an original word"*
  (right-click or command); a picker lists the verse's Greek/Hebrew words (manuscript form, parsing, gloss,
  Strong's) to click. Several English words can link to one original word.
- **Word popup** — hover/tap any tagged word for its **manuscript form + parsing**, **lemma**, meaning, and
  **root/derivation**.

**Study and write**
- **Your commentary** — *Bible: write a note on this verse* / *attach a note to selection*.
- **Ask the Bible** — semantic search for verses closest in meaning; **Save as study note** builds a
  topical note.
- **Reading plans** — *Bible: create a reading plan* (scope × days, dated checkboxes).
- **Quote a passage** — *Bible: insert a passage* embeds a live passage (prose flows; poetry keeps its
  hanging indent; mixed passages render each verse in its own shape).
- **Add a translation** — *Bible: paste a chapter*, with fields for poetry and paragraph breaks.
- **Annotate any version** — highlight, mark words of Christ red, tag a Strong's number, format as poetry.
- **Right-click** anywhere in a chapter for the **LoreMaster** menu of these commands.

## 9. Providers, privacy and settings

| I want to… | Do this |
|---|---|
| Change a setting | Sidebar **⚙** gear (or the service's control panel) |
| See/choose models | `vault:models`; routing defaults to **Auto** across free tiers |
| Find new free providers | `vault:discover-providers` → `vault:update-providers` (proposed, you approve) |
| Keep something local-only | **🔒 Private** toggle, or `private: true` frontmatter |

See [[Privacy-and-Settings]] for what leaves your machine and what never does.

## 10. Across devices

The service runs on one machine (desktop or a home box); Obsidian connects to it from anywhere on your
network or tailnet. On the **phone** you get the full reader, your notes and read-aloud; the heavier AI
work happens on the service. Point the plugin's **Host** at the machine running it. See [[Getting-Started]].

## 11. Housekeeping

| I want to… | Do this |
|---|---|
| Reload the plugin after an update | **Reload LoreMaster** (Obsidian's Ctrl+R often keeps the old code) |
| Refresh the command catalog | **Refresh Obsidian commands (sync to LoreMaster)** |
| Refresh these help notes | `vault:sync-help` |
| See what the service did | `vault:logs` |
| Run the self-test | `vault:test` |
| Take the tour | **LoreMaster: getting started (create a tour note)** |
