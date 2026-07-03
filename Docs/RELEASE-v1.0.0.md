# v1.0.0 — release & announcement pack

Copy-paste material for going public. **You** do the publishing steps (make the repo public, create the
release, post the announcements). Everything below is drafted and ready.

---

## Step 0 — make the GitHub repo public
GitHub → the `AI-Assistant` repo → **Settings → General → Danger Zone → Change visibility → Public**.
(Double-check `settings.json` was never committed — it's git-ignored, so it isn't; only
`settings.example.json` is in the repo. Good.)

## Step 1 — build the plugin binaries for the release
```bash
cd obsidian-plugin && npm run build      # produces main.js
```
Release assets = **`obsidian-plugin/main.js`**, **`obsidian-plugin/manifest.json`**,
**`obsidian-plugin/styles.css`** (BRAT downloads these three).

## Step 2 — create the GitHub Release
The `v1.0.0` tag already exists. Attach the three plugin files and paste the notes below.

Via the web UI: Releases → **Draft a new release** → choose tag `v1.0.0` → title `v1.0.0` → attach the
three files → paste **Release notes** (below) → Publish.

Or via the `gh` CLI (install from https://cli.github.com, then `gh auth login`):
```bash
gh release create v1.0.0 \
  obsidian-plugin/main.js obsidian-plugin/manifest.json obsidian-plugin/styles.css \
  --title "v1.0.0 — Zero-Cost AI Operating System for Obsidian" \
  --notes-file Docs/RELEASE-v1.0.0-notes.md
```

## Step 3 — announce (see drafts at the bottom)
Obsidian **Forum** → *Share & showcase*; Obsidian **Discord** → *#updates* / *#i-made-this*;
**r/ObsidianMD** on Reddit. Link the repo + release.

---

## Release notes (paste into the GitHub Release)

**Zero-Cost AI Operating System for Obsidian — v1.0.0**

An autonomous AI brain for your vault that runs entirely on **free-tier** AI providers — no subscription,
no per-token bill. A headless Python service reads and writes your vault, keeps its memory as Markdown,
and routes every request across free LLM tiers (Groq, Google AI Studio, Cerebras, NVIDIA). You talk to it
through an Obsidian **sidebar plugin** or by tagging a note.

**Highlights**
- 🧠 **Vault QA** — ask questions across your whole vault; local, GPU-accelerated embeddings; cited sources. Nothing leaves your machine.
- ✍️ **Propose/commit editing & restructuring** — the AI proposes edits and moves/renames/deletes as one-click **Approve/Reject** cards. It never changes your notes on its own.
- 🔒 **Privacy is a routing input** — mark a note `private` and it only goes to providers that don't train on your data (or stays fully local).
- 🌐 **Web research** — keyless web search → fetch → cited synthesis saved to your vault.
- 📎 **Ingest** PDFs/EPUB/Word, 🖼️ **OCR** images & handwriting, 🎙️ **transcribe** audio (local Whisper) — all searchable.
- 🕸️ **Knowledge graph**, 📖 **Scripture tooling** (passage guides), 🔎 **structured search**, 🎴 **spaced-repetition flashcards**.
- 🖥️ Runs headless (systemd on Linux); the laptop plugin can drive a home-server box over the LAN.

**302 automated tests · MIT licensed · install via BRAT** (below) + the Python service.

Install & full docs: see the README and `Docs/DEPLOYMENT.md`.

---

## Announcement — Obsidian Forum (Share & showcase)

**Title:** Zero-Cost AI Operating System for Obsidian — local Vault QA, propose/commit editing, free-tier only

Hi all — I've been building an AI assistant for Obsidian that runs on **free-tier AI providers only** (Groq,
Google AI Studio, Cerebras, NVIDIA) — so there's no subscription and no per-token cost. It's a small Python
service + a sidebar plugin.

What it does:
- **Vault QA** — semantic Q&A across your whole vault with cited sources; embeddings run locally (GPU-accelerated on an NVIDIA box). Your notes never leave your machine.
- **Propose/commit** — the AI *proposes* edits, and moves/renames/deletes, as Approve/Reject cards. It never edits your vault autonomously.
- **Privacy routing** — mark a note `private` and it only goes to providers that don't train on prompts, or stays fully local.
- Web research (cited), document ingestion, OCR, local audio transcription, a knowledge graph, structured search, and spaced-repetition flashcards.

It's MIT-licensed, has 302 automated tests, and I've been running it daily on a home Linux box driven from
my laptop. Install is via **BRAT** for now (Python-backend plugins don't fit the official directory yet).

Repo + docs: <REPO URL>
Feedback very welcome — it started as a Bible-study tool and grew into a general vault brain.

## Announcement — Discord (#i-made-this) / short

🚀 **Zero-Cost AI OS for Obsidian** (v1.0) — an AI brain for your vault that runs on **free-tier providers
only** (no subscription). Local, cited **Vault QA**; **propose/commit** editing + restructuring (Approve/
Reject cards, never autonomous); privacy-aware routing; web research, ingest, OCR, local transcription,
knowledge graph, flashcards. MIT, 302 tests, install via BRAT. Repo: <REPO URL>

## Announcement — r/ObsidianMD

**Title:** I built a zero-cost AI assistant for Obsidian (local Vault QA, propose/commit edits, free-tier only) — v1.0

Body: (same as the forum post, trimmed) — lead with "free-tier only, your notes stay local, the AI never
edits your vault without a one-click approval," then the feature list and the repo link.

---

## Plugin install instructions (for the README / release / posts)

**Prereq:** the Python service must be running (see `Docs/DEPLOYMENT.md` / `install/`).

1. Install **BRAT** (*Obsidian42 - BRAT*) from Community Plugins.
2. BRAT → **Add beta plugin** → paste `DocGRD/AI-Assistant`.
3. Enable **AI Assistant** in Community Plugins.
4. Open the AI Assistant sidebar → **⚙ Settings** → set **Host / Port / API token** to your Python service
   (localhost for the same machine, or the box's LAN IP + token).

---

## Later (optional) — official community directory
Needs: a unique plugin `id` (not the generic `ai-assistant`), `manifest.json`+`versions.json` reachable at
the release root, a release tag **`1.0.0`** (no `v`), and a PR to `obsidianmd/obsidian-releases`. The
external-Python-service requirement may draw review questions — a clear "how it works / what it sends where"
section helps. Simplest route: publish a **plugin-only companion repo** for the directory that points here
for the backend.
