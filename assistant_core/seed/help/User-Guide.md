<!-- help-version: 36 -->
# Loremaster — User Guide

*Current through **v1.9** (Milestones 1–40 + the v1.7–v1.9 UI/knowledge layer). Last updated: 2026-07-09.*

> **New since v1.6:** a self-updating, queryable **AI/Help** knowledge base and offline **read-aloud**
> (speed + voice + follow-along) with a non-blocking **dockable Approvals/Goals panel** (v1.7); **editable
> goal plans** (Re-plan / edit-before-approve), a Loremaster **editor right-click menu**, and `vault:reindex`
> (v1.8); **HTML-collection ingest** (`vault:ingest` a `.zip`/folder of interlinked `.htm` → notes with links
> rewritten to wikilinks), **`vault:logs`** self-diagnosis, and a self-seeding **complete system prompt** so
> the assistant knows every command (v1.9); and **Obsidian command-palette awareness** — Loremaster knows
> every command from Obsidian's core *and your installed plugins*, and can **propose running them** so it can
> use your plugins for you (v1.10).

Loremaster is a **zero-cost, local-first AI operating system for Obsidian**: a Python service on your machine
(or a home server) plus an Obsidian plugin. It chats, answers questions grounded in *your* vault, edits notes
with your approval, works proactively in the background, and never sends private notes to the web.

The day-to-day help set is **indexed** under `AI/Help/`, so you can also just **ask** "how do I …?" in chat.
Hubs: [[How-To-Use]] · [[Getting-Started]] · [[Commands]] · [[Features]] · [[Privacy-and-Settings]].

---

## 1. Set-up (once)
1. Start the Python service (`python -m assistant_core`) on your machine or home box — see [[DEPLOYMENT]].
2. In Obsidian, install the **Loremaster** plugin (via BRAT: `DocGRD/AI-Assistant`) and enable it.
3. Open plugin **Settings** → set **Host** / **Port** (and **API key** if the service is on another machine).
4. The sidebar header shows **Live** (green) when connected.

## 2. Chatting & Vault QA
- Type in the sidebar. Ask anything; add notes as context with **+ Note** or the **Related notes** dropdown.
- **Vault QA** (Actions menu) answers a question across your whole vault **with cited sources**, and won't
  invent `[[links]]` or facts your vault can't support.
- **Math** is answered deterministically (never guessed).

## 3. Editing & inline compose
- Select text in a note → **Actions → edit**, or ask in chat: Loremaster proposes a change as an
  **Approve / Reject** diff. Large selections are chunked so nothing is truncated.
- **Inline (hotkey) editing** — three editor commands open a preview popup (Accept / Regenerate / Cancel):
  - **Continue writing** — extends the text at your cursor.
  - **Rewrite selection** — rewrites the selected text per your instruction.
  - **Compose with Loremaster…** — free-form generate at the cursor.
  Inline editing uses **private routing** — your note text only goes to no-train/local providers.

## 4. Trust (nothing untrue enters the vault)
- Every note Loremaster **creates or edits** is checked: factual claims (numbers, dates, units) your vault
  can't support are flagged. `vault:contradictions` finds notes that disagree; the daily briefing surfaces them.
- Fabricated `[[links]]` are stripped; unsourced answers are escalated/web-cited or flagged ⚠.

## 5. Proactive layer — the 📥 Approvals inbox
Loremaster works quietly in the background (governor-paced, so it never competes with you or burns free-tier
limits) and **proposes** — it never changes notes on its own:
- **Auto-organize** suggests tags, related links, a better **folder**, or a **project** for recent notes.
- **Memory consolidation** proposes durable facts from your activity.
- Click the **📥 Approvals (N)** button → a modal lists everything pending. **Apply / dismiss each item**
  (per tag, per link, …) or Apply-all; **Open note** to inspect. Loremaster **learns** from what you accept
  or reject and tunes future suggestions.
- **🗞️ Briefing** opens today's read-only digest (focus, changes, due cards, pending approvals, vault health).

## 6. Goals — autonomous background work
- `vault:goal <description>` plans a multi-step goal; **approve** it and Loremaster runs one step per tick in
  the background. Templates: `--template research|digest|study`. Make it `--recurring weekly` or cap it with
  `--budget 20`.
- The **🎯 Goals (N)** button shows running goals with progress + **Pause / Resume / Cancel**.

## 7. Vault intelligence
- `vault:analytics` writes a read-only report: orphan notes, stale notes, unsourced notes, tag distribution,
  most-linked hubs, and near-duplicate tags worth merging.
- `vault:moc <topic>` proposes a Map-of-Content index note. `vault:actions <note>` extracts to-dos.

## 8. Capture
- `vault:clip <url>` (or the **Clip a web page** command) saves a page's readable text — or a **YouTube
  transcript** — as a sourced, indexed note in `AI/Clippings/`. Disabled in **Private** mode.
- `vault:template <name>` fills one of your Templater/Templates templates from context (propose-only).

## 9. Privacy
- The **🔒 Private** toggle (and `private: true` frontmatter) forces no-train/local providers and blocks all
  web steps for that turn. Clipping and web research are disabled while private. See [[Privacy-and-Settings]].

---
For every command see [[Commands]]; for feature walk-throughs see [[Features]]; for architecture and the
forward plan see [[Project-State]]; to verify features see [[AI/Tests/00-Test-Index]].