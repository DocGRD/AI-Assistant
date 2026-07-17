# Zero-Cost AI Operating System for Obsidian

A Python service that gives Obsidian an autonomous AI brain — one that reads and writes your
vault, keeps its memory as Markdown, and routes every request across **free-tier** AI providers
only. It runs headless in the background; you interact through the Obsidian sidebar plugin or by
tagging a note for the vault watcher. The terminal exists only for debugging.

> **Status: v1.9 (plugin "Loremaster") — Milestones 1–40 complete, 476 automated tests green.** Proven
> end-to-end: a headless Linux service (systemd, **GPU-accelerated** local embeddings) that the Obsidian
> sidebar plugin drives over the LAN with a token, running on a real ~2,300-note vault. Foundations (M1–M29):
> **propose/commit editing** (M9); registry-driven **privacy/task-aware providers** with a health floor (M10);
> zero-cost semantic **Vault QA** (M11) with **hybrid graph-aware retrieval** (M16); context UX (M12);
> quick actions + prompts (M13); project awareness (M14); self-testing (M15); provider registry (M16.7);
> memory "dreaming" (M17); knowledge graph (M18); OCR (M19); web research (M21); document ingestion (M22);
> Scripture intelligence (M24); provenance audit (M25); spaced-repetition study (M28); restructuring
> approve/reject (M29). **The v1.x arc (M30–M40) connected the toolbox:** **anti-hallucination** — fake-link
> killer, tier-aware routing, verify pipeline, **deterministic math** (M30–M32); **agent full-command access
> + autonomous web research** (M33); a **proactive processing layer** — daily briefing + auto-organize +
> resource governor (M34); an **autonomous goal engine** with templates/recurring/budgets (M35, M39); a
> **unified Approvals inbox** + connective-tissue linking + feedback learning (M36); **trust on every write**
> + contradiction detection (M37); **vault analytics / MOC / action-items** (M38–M39); **capture** — web +
> **YouTube** clipper, **Templater** typed-note fill (M40); and **immersive inline editing** + Approvals/Goals
> **badge-buttons** (v1.6). **v1.7–v1.9 added:** a **self-updating, queryable AI/Help knowledge base** and
> **offline read-aloud** (speed + voice + follow-along) with a **non-blocking dockable Approvals/Goals panel**
> (v1.7); **editable/iterable goal plans** + a Loremaster **editor right-click menu** + `vault:reindex` (v1.8);
> **HTML-collection ingest** (`.zip`/folder of interlinked `.htm` → notes with links rewritten to wikilinks),
> **`vault:logs`** self-diagnosis, and a **self-seeding, complete system prompt** so the model knows every
> command (v1.9). Full specs in [`Docs/Project-State.md`](Docs/Project-State.md);
> the user guide is [`Docs/User-Guide.md`](Docs/User-Guide.md); install in [`Docs/DEPLOYMENT.md`](Docs/DEPLOYMENT.md).

---

## What it does today

**Core.** Headless by default (a vault watcher + local HTTP API, no terminal); reads and writes the vault
through a shared agent loop (`MAX_STEPS = 10`) used by all three entry points; memory as plain Markdown
under `AI/` — system/web prompts, user profile, learned facts, per-project notes, and crash-safe daily
episode logs. A live **task ledger** (`AI/System/Task-State.md`) records each step so a switched provider
resumes the same plan and you can watch/resume after a crash.

**Providers (zero-cost).** Registry-driven routing across free tiers (Groq, Google AI Studio, Cerebras,
NVIDIA; OpenRouter as a candidate) via **one** generic OpenAI-compatible adapter — adding a provider is a
Markdown edit in `AI/System/Provider-Registry.md`. Selection is **privacy- and task-aware** (`private`
turns route only to no-train providers; large jobs prefer high-volume providers). **Health floor:** a
provider that fails on real traffic is skipped, with a warning below three healthy. **Self-discovering
registry** (`vault:discover-providers`) proposes a registry from each provider's live `/models` (chat
models capability-tagged; embedding/whisper/etc. kept in a separate table), and a weekly scheduler runs it
— always propose/commit.

**Vault tools.** Read / search / list / **find** (recursive glob) / links / create / update, plus
**restructuring** — `vault:copy` / `vault:move` / `vault:trash` (recoverable) / `vault:mkdir` — all
path-jailed inside the vault. **Context-aware editing (M9)** and **restructuring (M29)** are propose/commit:
the agent only *proposes* a change (an edit diff, or a one-click **Approve/Reject** card for a move/rename/
delete); you commit it in the plugin. Nothing consequential runs autonomously.

**Retrieval & context.** Zero-cost local **Vault QA** (`vault:ask` / 📚 toggle) with **hybrid** ranking
(vector + `[[links]]` + `#tags`) and cited source chips; `@`-note mentions, a Related-notes dropdown, and
folder/tag-scoped QA ("project mode"). Embeddings are local (fastembed / `bge-small`) and **GPU-accelerated**
on a CUDA box, CPU everywhere else.

**Bible study reader.** The public-domain **World English Bible** ships as folder-ordered notes
(`bible/{NN}-{book}/{version}/…`, sourced from USFM so poetry, paragraphs, and section headings are
preserved), read in a classic serif study-Bible layout. The plugin renders three distinct link layers over
scripture: **cross-references** (public-domain OpenBible, stored once and version-independent, injected as
quiet superscript markers — hover for the verse, click to open it, click a verse number for *all* of them)
and **"Related by meaning"** (embedding-similarity passages, dashed links, deduplicated against the
cross-references). Verse-by-verse ⟷ flowing-paragraph layouts, auto-Reading-view, and a configurable
cross-reference count. Scripture and imported commentary (e.g. Matthew Henry) are in the semantic index, so
`vault:ask` searches God's word. Adding another translation is a paste into the standard note format — the
cross-references and related links then appear automatically. (Copyrighted translations like ESV/NASB/NKJV
are used only within their terms; WEB is the bundled public-domain base.)

**Research round-trip.** `vault:research` generates a prompt for a web AI; when you paste the answer back,
the assistant saves it **verbatim** to `AI/Research/`, gives it a short LLM-generated title, produces a
2-3 sentence summary, and links **real** related notes from the index — no fabricated links, no loop.

**Memory / "dreaming" (M17).** A nightly pass turns episodes into durable facts (forced-private
extraction, embedder-deduped) as a review proposal, archives old episodes into monthly digests, and long
chats compress via summary blocks instead of dropping context. The plugin's **Memory review** panel
accepts/rejects proposed facts.

**Media (M19).** `vault:ocr` extracts text from a note's images and handwriting (free multimodal model +
local tesseract fallback) into an additive `AI/Derived/` sidecar; Excalidraw drawings are indexed by their
typed text. Both become searchable in Vault QA. Privacy: a private note's images stay on no-train models
or local OCR.

**Knowledge graph (M18).** `vault:graph` (and an opt-in nightly build) extract entities/relations into
linked Markdown under `AI/Graph/Entities/` — browsable in Obsidian's own graph view and in the plugin's
**Graph** viewer (a radial subgraph popup served by `GET /graph`).

**Scheduling.** An in-process daemon runs weekly discovery + nightly consolidation/graph — **no OS cron**,
cross-platform, all propose/commit. Plus self-testing (`vault:test`) and allow-listed propose/commit
scripts (M15), and a runtime **control panel** in the plugin (edit `settings.json` + restart).

## Interfaces

- **Plugin sidebar** (primary): live chat over HTTP (LAN + token supported) with a vault-file fallback
  (Vault mode via the watcher). Provider dropdown + 🔒 Private toggle on the title bar, a **Related-notes**
  dropdown (add any to context), an **Actions ▾** menu on the send line (Vault QA, Summarize/Key points/
  Action items, Fix grammar/Improve, Prompts…, Graph), 📎 attach, the Memory-review panel, and the Graph
  viewer. Edit/restructure proposals render inline with Replace / Keep editing / **Cancel**.
- **Vault watcher** (primary): set `assistant-status: pending` + `assistant-request: <question>` on any
  note; the watcher processes it and writes back.
- **Terminal** (debug only): `python -m assistant_core --terminal`.

## Run it

```bash
# Headless (same as production)
python -m assistant_core          # or: python assistant.py  (back-compat shim)

# Interactive terminal (debugging)
python -m assistant_core --terminal

# One-shot maintenance (also run nightly/weekly by the in-process scheduler)
python -m assistant_core --consolidate [--apply]     # dreaming: episodes -> durable facts
python -m assistant_core --build-graph [--limit N]   # incremental knowledge-graph build

# Shutdown / restart
curl http://127.0.0.1:8765/shutdown   # or: sudo systemctl restart assistant
```

**Install.** *Python service:* one-command scripts — `install/install.ps1` (Windows) and
`install/install.sh` (Linux; `--service` sets up the `systemd` unit, `--gpu` the CUDA-12 embedding extras).
Then edit `settings.json`. *Obsidian plugin:* install it with **BRAT** (*Obsidian42 - BRAT* → Add beta
plugin → `DocGRD/AI-Assistant`), enable **AI Assistant**, and point its ⚙ settings at the service (localhost,
or the box's LAN IP + token). Deployment model: Windows for development, Linux (systemd) for production;
Obsidian Sync keeps the vault identical across machines. Full install, GPU setup, LAN + token, background
maintenance, and per-milestone tests are in the **[Deployment & Test Guide](Docs/DEPLOYMENT.md)**;
release/announcement material in **[Docs/RELEASE-v1.0.0.md](Docs/RELEASE-v1.0.0.md)**.

---

## Architecture (high level)

```
assistant.py        back-compat shim → assistant_core.app:main
assistant_core/     the service package (run: python -m assistant_core)
  app.py            bootstrap + terminal loop — headless default, watcher + HTTP + scheduler threads
  server/           FastAPI HTTP API (core, models, suggestions)
  agent_loop.py     shared agent loop (terminal, server, watcher); MAX_STEPS=10; task ledger
  task_ledger.py    M20 externalized task/planner state (+ AI/System/Task-State.md)
  research_roundtrip.py  M20 verbatim-save + non-agentic summary + real related notes + title
  consolidation.py  M17 dreaming: episodes -> durable-fact proposals + episode archival
  scheduler.py      M16.7/M17 in-process maintenance (weekly discovery + nightly consolidation/graph)
  paths.py          on-disk anchors + resolve_in_vault path jail (M16.6)
  episodes.py / diagnostics.py / vault_commands.py
  providers/        base_provider, provider_router, model_registry, generic OpenAI adapter (M10),
                    registry_loader, model_discovery, discovery_job, registry_proposer (M16.7),
                    webui_provider (web handoff)
  memory/           memory_manager (prompts + episodes), context_manager (summary-based compression)
  tools/            read/search/list/find/links/create/update, file_ops (copy/move/trash/mkdir),
                    research/import/summarise, provider_tracker
  editing.py        M9 propose/commit edit helpers
  rag/              M11/M16 Vault QA — local embeddings, numpy index, hybrid retriever, RagService
  media/            M19 excalidraw text + ocr (multimodal + tesseract); M27 audio (local Whisper)
  graph/            M18 extractor (triples) + store (Markdown entity notes) + job (build) + M23 guides
  web/              M21 web research — multi-provider search, fetch, cited synthesis
  ingest/           M22 document ingestion (PDF/EPUB/DOCX/txt → AI/Library, page anchors)
  scripture/        M24 reference parsing + Passage Guide
  provenance.py     M25 source audit (vault:sources)
  query.py          M26 structured/exact search (vault:query)
  study/            M28 flashcards + SM-2 spaced repetition
  testing/          gui_harness — desktop-GUI E2E harness + zero-cost ground-truth oracle
  watcher/          vault_watcher, request_handler (agent loop), frontmatter_parser
  config/           config_manager (settings.json + repo-root fallback), logger
obsidian-plugin/    main.ts, ChatView.ts (chat, control panel, Related/Memory-review panels, Graph viewer)
```

Vault system files live under `AI/System/` (`Project-State.md`, `System-Prompt.md`, `WebUI-Prompt.md`,
`Provider-Registry.md`, `Task-State.md`); derived data under `AI/Memory/`, `AI/Graph/`, `AI/Derived/`.

---

## Standing design principles

- **Zero cost.** Free tiers only; the router enforces it; embeddings/OCR/graph run locally.
- **Obsidian is the knowledge base.** Nothing important lives in binary files or databases.
- **Python for the brain, TypeScript for the face.** They talk over HTTP only.
- **Tools produce real results, not claimed ones.** Tool output is injected back into context before the reply.
- **Privacy is a routing input.** Notes flagged `private` go only to providers that don't train on/log prompts (and web/OCR/audio stay local or no-train).
- **Propose/commit for anything consequential.** Edits, provider changes, consolidated facts, and scripts are proposed for review — never applied autonomously.

---

## Roadmap — M21–M29 ✅ (complete)

A 2026-07 review of the assistant against everyday Obsidian use and **modern Bible study software**
surfaced twelve capability gaps. These milestones closed them, keeping the zero-cost / privacy-forced /
propose-commit discipline. **All are implemented and tested (302 automated tests green).** Full specs
in [`Docs/Project-State.md`](Docs/Project-State.md).

- ✅ **M21 — Web-Capable Research.** `vault:webresearch` — config-driven multi-provider web search
  (keyless DuckDuckGo / SearXNG; Brave / Serper / Tavily / Exa / Google CSE when keyed) → fetch → **cited**
  synthesis + verbatim sources under `AI/Research/`. Privacy-forced; `vault:research` remains as fallback.
- ✅ **M22 — Document Ingestion.** `vault:ingest` extracts PDF / EPUB / DOCX / txt → `AI/Library/` with
  per-page provenance anchors, indexed for Vault QA. The 📎 paperclip attaches vault files.
- ✅ **M23 — Graph-Aware Retrieval & Guides** (delivered with M18). `vault:guide <topic>`, entity browser,
  and `vault:graph-merge` alias-dedup.
- ✅ **M24 — Scripture Intelligence.** `vault:passage <ref>` — Bible references parsed/normalised, notes
  gathered by verse-range overlap, and a **cited Passage Guide** assembled from your notes.
- ✅ **M25 — Provenance & Citations.** Sources recorded across consolidation/graph/web/ingest, plus
  `vault:sources <claim>` — audits which notes support a statement and flags unsourced claims.
- ✅ **M26 — Structured & Exact Search.** `vault:query` — `tag:` / `path:` / `fm:key=value` / `"phrase"` /
  `A NEAR/n B`, complementing semantic Vault QA.
- ✅ **M27 — Audio Transcription.** `vault:transcribe` — sermon/lecture audio → searchable text via **local**
  Whisper (offline, free; audio never leaves the machine).
- ✅ **M28 — Study Reinforcement.** `vault:cards` / `vault:review` — flashcards generated from a note and
  scheduled with SM-2 spaced repetition.
- ✅ **M29 — Restructuring propose-and-approve.** Ask in plain language to move / rename / remove / file a
  note; the agent stages the `vault:copy` / `:move` / `:trash` / `:mkdir` as a one-click **Approve / Reject**
  card. Nothing changes until you approve (`trash` is recoverable).

### Deferred / long-term

Task harvester (vault-wide `- [ ]` → Todo note); multi-agent roles (researcher / planner / coder /
reviewer).

## Explicit non-goals

Never train or fine-tune models. Never store critical information in proprietary databases. Always:
**Vault → Memory → Retrieval → Context → existing LLMs.**

---

## License

MIT — see [`LICENSE`](LICENSE). Free to use, modify, and redistribute (including commercially), with
attribution.
