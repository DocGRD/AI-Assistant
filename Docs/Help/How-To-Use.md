---
tags: [help, user-guide]
---
# How to Use the AI Assistant

*The complete, current guide (Milestones 1–22). These `AI/Help/` notes are **indexed**, so you can also
just ask the assistant "how do I …" and it will answer from them.*

The assistant is a zero-cost AI brain for this vault: it reads and writes your notes, keeps its memory as
Markdown, and routes every request across **free-tier** providers only. You talk to it three ways — the
**Obsidian sidebar plugin** (live chat), the **vault watcher** (tag a note and it answers), and the
**terminal** (debug/admin).

## Guide contents
- [[Getting-Started]] — install, run, connect the plugin, first chat.
- [[Commands]] — every `vault:` command, what it does, and where to type it.
- [[Features]] — task-by-task: editing, search & Vault QA, research, web, documents, images, the graph,
  guides, memory.
- [[Privacy-and-Settings]] — the 🔒 Private toggle, providers, the settings panel, nightly automation.

## "How do I …?" — quick answers

| I want to… | Do this | More |
|---|---|---|
| Chat with it | Open the **AI Assistant** sidebar, type, Send | [[Getting-Started]] |
| Ask a question across my whole vault | **Actions ▾ → Vault QA**, then ask | [[Features]] §Search |
| Find a note by keyword | `vault:search <words>` | [[Commands]] |
| Have it improve/rewrite selected text | Select text → **Actions ▾ → Fix grammar / Improve** → **Replace** (or **Cancel**) | [[Features]] §Editing |
| Reorganise / move / rename / delete a note | Ask in plain language → **Approve** the change card | [[Features]] |
| Add related notes to the chat | **Related notes ▾** dropdown → click each to add | [[Features]] |
| Pull specific notes into the chat | `@` / **+ Note**, or type `vault:read <note>` | [[Features]] |
| Research something on the web (auto) | `vault:webresearch <question>` | [[Features]] §Research |
| Research with my own web AI (manual) | `vault:research <question>`, paste the answer back | [[Features]] §Research |
| Bring a PDF / EPUB / Word doc into the vault | 📎 paperclip → pick it, or `vault:ingest <file>` | [[Features]] §Documents |
| Attach a file quickly | Click the **📎** by the input → document is ingested, image is analysed | [[Features]] |
| Read text out of an image / handwriting | `vault:ocr <note>`, or 📎 an image | [[Features]] §Images |
| Analyse/describe a single image | 📎 pick the image, or `vault:analyze <image>` | [[Features]] §Images |
| See how my notes connect | **Graph** button, or `vault:graph <note>` then browse | [[Features]] §Graph |
| Get everything I know about a topic | `vault:guide <topic>` | [[Features]] §Graph |
| Keep something private | Toggle **🔒 Private**, or add `private: true` to the note | [[Privacy-and-Settings]] |
| Change a setting | Sidebar **⚙** gear → settings | [[Privacy-and-Settings]] |
| Run the test suite | `vault:test` (terminal) | [[AI/Tests/00-Test-Index]] |

> Golden rule: the assistant only claims it did something when a real tool result backs it up, and it
> **never overwrites a note on its own** — edits, provider changes, and consolidated facts are always
> proposed for you to accept.
