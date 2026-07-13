<!-- help-version: 29 -->
---
tags: [help, user-guide, whats-new]
---
# What's New in Loremaster

*A capability overview so you can learn everything Loremaster can do. Current through **v1.10.15**.*

## Loremaster understands itself + robust handling of huge notes (v1.10.13–v1.10.15)
- **Everyday replies are much faster (v1.10.15).** A routing bug tiered every Gemini model as
  "small" (the word "gemini" contains "mini"!), which quietly benched Google's fast, high-capacity
  Flash models on tool/agent turns — so normal requests were stuck on small per-minute limits and
  fell back to a slow provider, sometimes timing out. Fixed: Gemini is tiered correctly and now
  carries everyday turns quickly (non-private only — it's never used for private notes).
- **Loremaster now knows what it is and how it works** — its architecture (a Python service + this Obsidian
  plugin), where everything lives in your vault (`AI/Memory/Episodes/`, `Learned-Facts`, proposals, reports…),
  and its own memory lifecycle (nightly consolidation + the **30-day episode archival** window). So questions
  like "why isn't this episode archived?" or "where are my facts stored?" get correct answers instead of guesses
  — and it answers them **from what it knows**, instead of reflexively opening a huge status file.
- **A large read no longer stalls a reply.** Only a genuinely context-threatening read (tens of KB) is
  condensed now — a normal search or list result passes straight through (condensing a list would lose items).
  When condensing *is* needed it **map-reduce summarizes** (chunk → summarize each → combine, steered by your
  question) so key points survive instead of being blind-truncated. (Toggle: `condense_large_reads`.)
- **The free local model can no longer hang a request.** If the on-device model times out once (e.g. the home
  server's GPU is busy), Loremaster backs off it for a few minutes and uses the cloud router instead — so a
  simple request can't sit for minutes waiting on a stuck local model.
- **Hardening:** the full system prompt is now single-sourced (a stale hidden fallback copy that could drift
  out of sync was removed), so what the assistant knows about itself and its commands stays consistent.

## Explained link suggestions + readable Approvals (v1.10.1)
- **Suggested links now come with a reason** — *and only genuinely-related links are suggested.* When
  Loremaster proposes a related note (auto-organize or `vault:organize <note>`), it explains *why* it's
  related, grounded in the actual content of both notes, and you see that reason under each link in the
  **📥 Approvals** panel before you decide. It also **drops self-links and any candidate it judges
  unrelated**, so cross-domain noise from the semantic index no longer clutters your suggestions.
- **Reasons are written into the note.** Applying the links adds a **`| Links | Reason |` table** under a
  `## Related` heading, so the rationale lives beside the link in your note (not just in the panel).
- **The Approvals panel now wraps text** — long note names and reasons are fully visible instead of being
  cut off.
- **Loremaster understands your plugins better** — the command catalog now carries each plugin's description
  (what it's for), so it picks the right command more reliably. (Obsidian exposes no per-command help text,
  so individual commands are still understood from their name + id.)

## Loremaster can use your Obsidian plugins (v1.10)
- **Loremaster now knows your whole Obsidian command palette — core *and* every community plugin you
  install** — and can run those commands for you. Ask in plain language ("insert my daily-note template",
  "open the calendar", "create a new Excalidraw drawing") and it finds the matching command and **proposes**
  running it: a one-click **Approve & run** card. The plugin executes it (the service can't reach Obsidian's
  commands), and destructive/outward-facing commands (delete, publish, sync) are flagged with a ⚠ — nothing
  runs until you approve.
- **New plugins are picked up automatically.** Install or enable a plugin and its commands become available
  to Loremaster with no setup (there's also a **Refresh Obsidian commands** palette command to force it).
- **Commands & tools are routed to reliable models (v1.10.4).** Running a command needs the assistant to emit
  a precise directive; some "reasoning" models (which think out loud) mangle that format. Loremaster now
  keeps tool/command turns on models that follow the format cleanly and skips reasoning models for those
  turns — so commands and vault actions work consistently. (Toggle with `tool_reliable_routing`.)
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
