<!-- help-version: 22 -->
---
tags: [help, user-guide, whats-new]
---
# What's New in Loremaster

*A capability overview so you can learn everything Loremaster can do. Current through **v1.10**.*

## Loremaster can use your Obsidian plugins (v1.10)
- **Loremaster now knows your whole Obsidian command palette — core *and* every community plugin you
  install** — and can run those commands for you. Ask in plain language ("insert my daily-note template",
  "open the calendar", "create a new Excalidraw drawing") and it finds the matching command and **proposes**
  running it: a one-click **Approve & run** card. The plugin executes it (the service can't reach Obsidian's
  commands), and destructive/outward-facing commands (delete, publish, sync) are flagged with a ⚠ — nothing
  runs until you approve.
- **New plugins are picked up automatically.** Install or enable a plugin and its commands become available
  to Loremaster with no setup (there's also a **Refresh Obsidian commands** palette command to force it).
- Under the hood: `command:search <query>` finds commands, `command:run <id>` proposes one. You rarely type
  these — just ask.

## Read-aloud on mobile + clearer errors (v1.9.1–v1.9.3)
- **Read-aloud now works on Android.** Obsidian's mobile WebView has no built-in speech, so the
  service synthesizes the audio (a local **Piper** neural voice, or espeak) and the plugin plays it —
  Play/Pause/Stop and speed all work. Desktop still uses the instant built-in voice. Zero-cost, local,
  private (audio never leaves your machine/LAN). **"Read note aloud"** now also appears in the mobile
  command palette (it was hidden in reading view before).
- **Chat errors are now informative** — a timeout / unreachable service / provider failure shows a
  clear reason and a hint (e.g. run `vault:logs errors`) instead of a bare red "Error".

## Import HTML sets + self-diagnosis + smarter prompt (v1.9)
- **Ingest a `.zip` of HTML** (or a folder of them) — e.g. an offline commentary export. Every file
  becomes a vault note under `AI/Library/<collection>/`, and the **inter-file links are rewritten to
  point at the new notes** (wikilinks), so the whole set stays navigable inside Obsidian.
- **`vault:logs [N | errors | today]`** lets Loremaster **read its own logs** (`logs/assistant.log`,
  outside the vault) to diagnose when something goes wrong — and the assistant can pull them itself.
- **The assistant now knows its full command set.** The system prompt is packaged, version-stamped and
  self-updating, so the model is aware of every command (goals, analytics, clip, briefing, …) and no
  longer forgets the newer ones.
- **Fixed:** the 📥 Approvals / 🎯 Goals side panel could open blank; it now always shows your items.

## Editable goal plans + right-click menu + reindex (v1.8)
- **Refine a goal's plan before you approve it.** When Loremaster plans a goal it's *proposed*, not running.
  Iterate until it's solid: click **Re-plan** in the Approvals panel (or `vault:goal replan <slug> :: <feedback>`)
  to have it revise the steps, and/or **Open note** and edit the `- [ ]` steps yourself — **approve honors your
  edits**. Cycle as many times as you like, then approve to run it.
- **Right-click menu:** the editor context menu now has **Loremaster: Read aloud / Rewrite selection /
  Continue writing / Compose…**.
- **`vault:reindex [full]`** rebuilds the Vault QA index on demand.

## Read-aloud (v1.7)
- **Read a note aloud** (editor command) — reads the selection if you've highlighted text, else the whole
  note. A **floating control bar** gives Play/Pause/Stop, previous/next sentence, **speed presets**
  (0.75× / 1× / 1.25× / 1.5× / 2×), and a **voice picker** (whatever voices your OS has).
- The sentence being spoken is **highlighted and scrolled into view** as it reads.
- Every chat reply from Loremaster has a **🔊 button** to hear it read aloud (highlighted in the bubble).
- Fully **offline / on-device / private** — audio never leaves your machine.

## Self-updating help (v1.7)
- These `AI/Help/` notes now **refresh automatically** with each release, and are **indexed** — so asking
  "how do I …?" always reflects the current version. `vault:sync-help` refreshes them on demand.

## Approvals & Goals side panel (v1.7)
- The **📥 Approvals** and **🎯 Goals** badge-buttons open a **dockable side panel** (not a pop-over), so
  clicking **Open note** shows the note beside the panel instead of covering it.

## Immersive inline editing (v1.6)
- **Continue writing / Rewrite selection / Compose with Loremaster…** — a popup previews the AI's text; you
  **Accept / Regenerate / Cancel**. Private routing (your note text never goes to the web).

## Trust — nothing untrue enters the vault (M30–M37)
- Fake `[[links]]` are stripped; **math** is computed deterministically; unsourced answers are escalated /
  web-cited / flagged ⚠. Every **created/edited** note has its factual claims checked (`write_guard`).
- `vault:contradictions` flags notes that disagree on a number/date or via negation.

## Proactive layer (M34) + the Approvals inbox (M36)
- Background, governor-paced: a **Daily Briefing**, and **auto-organize** proposing tags, related links, a
  better **folder**, and a **project** — all collected in the **Approvals inbox** with per-item apply/dismiss
  and **feedback learning**. Memory "dreaming" proposes durable facts too.

## Autonomous goals (M35, M39)
- `vault:goal` plans a multi-step goal you approve; it runs one step per tick in the background. **Templates**
  (research / digest / study), **recurring** goals, per-goal **budget caps**, and subtask **dependencies**.

## Vault intelligence (M38)
- `vault:analytics` (orphans, stale, unsourced, hubs, near-duplicate tags), `vault:moc <topic>`,
  `vault:actions <note>`.

## Capture (M40)
- `vault:clip <url>` saves web pages **and YouTube transcripts**; `vault:template` fills Templater templates.

## Foundations (M1–M29)
- Grounded chat + **Vault QA** with hybrid retrieval; propose/commit **editing** + **restructuring**;
  knowledge **graph**; **web research**; document **ingestion**; **OCR**; **Scripture** intelligence;
  **provenance** audit; **spaced-repetition** study; zero-cost privacy/task-aware provider routing.

See [[Commands]] for exact syntax and [[Features]] for task walkthroughs.
