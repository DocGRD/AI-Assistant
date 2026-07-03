## Zero-Cost AI Operating System for Obsidian — v1.0.0

An autonomous AI brain for your vault that runs entirely on **free-tier** AI providers — no subscription,
no per-token bill. A headless Python service reads and writes your vault, keeps its memory as Markdown, and
routes every request across free LLM tiers (Groq, Google AI Studio, Cerebras, NVIDIA). You talk to it
through an Obsidian **sidebar plugin** or by tagging a note.

### Highlights
- 🧠 **Vault QA** — ask questions across your whole vault; local, GPU-accelerated embeddings; cited sources. Nothing leaves your machine.
- ✍️ **Propose/commit editing & restructuring** — the AI proposes edits and moves/renames/deletes as one-click **Approve/Reject** cards. It never changes your notes on its own.
- 🔒 **Privacy is a routing input** — mark a note `private` and it only goes to providers that don't train on your data (or stays fully local).
- 🌐 **Web research** — keyless web search → fetch → cited synthesis saved to your vault.
- 📎 **Ingest** PDFs/EPUB/Word, 🖼️ **OCR** images & handwriting, 🎙️ **transcribe** audio (local Whisper) — all searchable.
- 🕸️ **Knowledge graph**, 📖 **Scripture tooling** (passage guides), 🔎 **structured search**, 🎴 **spaced-repetition flashcards**.
- 🖥️ Runs headless (systemd on Linux); the laptop plugin can drive a home-server box over the LAN.

**302 automated tests · MIT licensed.**

### Install
1. Python service — `install/install.ps1` (Windows) or `install/install.sh` (Linux); edit `settings.json`; see `Docs/DEPLOYMENT.md`.
2. Obsidian plugin — via **BRAT**: install *Obsidian42 - BRAT* → *Add beta plugin* → `DocGRD/AI-Assistant` → enable **AI Assistant** → point its ⚙ settings at the Python service.
