<!-- help-version: 37 -->
---
tags: [help, user-guide]
---
# How to Use Loremaster

*Current through v1.7. These `AI/Help/` notes are **indexed**, so you can also just ask "how do I …?" in
chat and Loremaster answers from them. (They're kept up to date automatically — run `vault:sync-help` to
refresh on demand.)*

Loremaster is a zero-cost, local-first AI brain for this vault: it reads and writes your notes, keeps its
memory as Markdown, works proactively in the background, and routes every request across **free-tier**
providers only. Private notes never leave your machine.

## Guide contents
- [[Getting-Started]] — install, run, connect the plugin, first chat.
- [[Commands]] — every `vault:` command.
- [[Features]] — task-by-task walkthroughs.
- [[Privacy-and-Settings]] — the 🔒 Private toggle, providers, settings, nightly automation.
- [[Whats-New]] — the latest capabilities (proactive layer, goals, trust, capture, read-aloud, …).
- [[User-Guide]] — the full end-to-end guide.

## "How do I …?" — quick answers

| I want to… | Do this |
|---|---|
| Chat | Open the **Loremaster** sidebar, type, Send |
| Ask across my whole vault | **Actions ▾ → Vault QA**, then ask (cited, grounded) |
| Find a note | `vault:search <words>` |
| Rewrite / continue text in place | Select text → command **Rewrite selection (inline)** / **Continue writing (inline)** → preview → Accept |
| Edit a note via chat | Select text → **Actions ▾ → edit**, or ask; **Approve** the diff |
| Reorganise / move / rename / delete | Ask in plain language → **Approve** the change card |
| Review background suggestions | Click **📥 Approvals** (badge shows the count) → a docked side panel; apply/dismiss per item |
| See running goals | Click **🎯 Goals** → pause / resume / cancel |
| Read today's digest | Click **🗞️ Briefing** |
| Start an autonomous goal | `vault:goal <description>` (`--template research\|digest\|study`, `--recurring`, `--budget`) → approve it |
| Research the web (auto) | `vault:webresearch <question>` |
| Save a web page or YouTube video | `vault:clip <url>` (or the **Clip a web page** command) |
| Fill one of my templates | `vault:template <name> :: <context>` |
| Bring a PDF / EPUB / Word doc in | 📎 paperclip, or `vault:ingest <file>` |
| Read text out of an image | 📎 an image, or `vault:ocr <note>` |
| See how notes connect | **Graph** button, or `vault:graph <note>` |
| Get everything on a topic | `vault:guide <topic>` or `vault:moc <topic>` |
| Understand my vault | `vault:analytics` (orphans, stale, hubs, tag merges) |
| Find conflicting notes | `vault:contradictions` |
| Pull to-dos out of a note | `vault:actions <note>` |
| **Read a note aloud** | Command **Read note aloud** (or 🔊 on a chat reply) → floating bar with **speed** + **voice** |
| Keep something private | Toggle **🔒 Private**, or add `private: true` to the note |
| Change a setting | Sidebar **⚙** gear |

> Golden rule: Loremaster only claims it did something when a real tool result backs it up, and it **never
> overwrites a note on its own** — edits, moves, provider changes, and background suggestions are always
> **proposed for you to approve**.
