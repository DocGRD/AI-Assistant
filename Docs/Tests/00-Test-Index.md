# AI Assistant — Test Suite Index

**Project:** Zero-Cost AI Operating System for Obsidian  
**Purpose:** Systematic verification of every feature across all completed milestones  
**How to use:** Work through each file in order. Mark each test ✅ Pass, ❌ Fail, or ⏭ Skip. Record notes in the Notes field. A failed test gets a bug note and a fix attempt before moving on.

---

## Test Files

| File | Milestone | Focus |
|------|-----------|-------|
| [[AI/Tests/completed/M1-Foundation-Tests]] | 1 + 1.5 | Startup, config, logging, diagnostics |
| [[AI/Tests/completed/M2-Provider-Tests]] | 2 | Groq + Google AI, routing, fallback |
| [[AI/Tests/completed/M3-Vault-Access-Tests]] | 3 + 3-patch | Vault read tools, vault commands, verbose |
| [[AI/Tests/completed/M4-Router-Memory-Tests]] | 4 + 4-patch | Token routing, memory, context trimming, episodes |
| [[AI/Tests/completed/M5-Research-Tests]] | 5 | Research workflow: generate, import, summarise |
| [[AI/Tests/completed/M5-5-Watcher-Tests]] | 5.5 | Vault watcher, frontmatter triggers, chunking |
| [[AI/Tests/completed/M6-Plugin-Tests]] | 6 | HTTP server, Obsidian plugin, vault-mode fallback |
| [[AI/Tests/completed/M7-Handoff-Tests]] | 7 | Web handoff, provider override, history lock |
| [[M9-Editing-Tests]] | 9 | Propose/commit editing — selection, dialog, vault staging, privacy |
| [[M10-Provider-Routing-Tests]] | 10 | Registry routing, privacy + task selection, tracker, health floor |
| [[M11-VaultQA-Tests]] | 11 | Vault QA (local RAG) — indexing, ask + sources, privacy, LAN |
| [[M12-Context-Tests]] | 12 | Context UX — @-mentions, related notes, scoped Vault QA |
| [[M13-14-Quick-Project-Tests]] | 13–14 | Quick commands, prompts, project awareness |
| [[M15-SelfTest-Scripts-Tests]] | 15 | `vault:test`, propose/commit scripts |
| [[M16-Hybrid-Retrieval-Tests]] | 16 | Hybrid (graph-aware) Vault QA — link/tag boost, source labels, privacy |
| [[M17-Dreaming-Tests]] | 17 | Nightly consolidation, archival, Memory-review, context summarization |
| [[M18-Knowledge-Graph-Tests]] | 18 + 23 | Entity graph, plugin viewer + browser, `vault:guide`, alias merge (M23 graph-aware guides fold in here) |
| [[M19-Media-OCR-Tests]] | 19 | Excalidraw text, image/handwriting OCR sidecars, privacy |
| [[M20-Planner-Research-Tests]] | 20 | Deliverable tools, Task-State ledger, research paste-back |
| [[M21-Web-Research-Tests]] | 21 | `vault:webresearch` — multi-provider search, cited synthesis, privacy |
| [[M22-Document-Ingestion-Tests]] | 22 | `vault:ingest` — PDF/EPUB/DOCX → indexed AI/Library |
| [[M24-M28-Study-Search-Tests]] | 24–28 | Scripture passages, provenance audit, structured search, audio, flashcards |
| [[E2E-Scenario-Tests]] | all | Human/GUI end-to-end scenarios (also driven by the desktop-automation harness) |
| [[GUI-Test-Plan-Exhaustive]] | **all (v1.10.4)** | **Standing exhaustive desktop-automation GUI plan — edge-case & weak-spot hunt (W1–W12 risk map, 20 functional + 10 non-functional suites, P0 safety-first, fuzz matrix). Run this every release.** |

See also [[User-Guide]] for day-to-day usage, and [[Deployment-Guide]] for install/config plus the
exact command to run each milestone's tests.

**Run all automated tests at once:** `python -m assistant_core --terminal` → `vault:test`
(or `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover -s tests`).

---

## Test Result Summary

> The authoritative regression check is the **automated suite: 302 tests** — run `vault:test`, or
> `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover -s tests`. The table below is a
> legacy manual-acceptance tracker (per the human test docs); the counts are for those manual walkthroughs,
> not the automated suite.

Copy this into each session to track progress.

| Milestone | Total Tests | Pass | Fail | Skip | Status |
|-----------|-------------|------|------|------|--------|
| M1 + M1.5 | 18 | | | | |
| M2 | 16 | | | | |
| M3 + patch | 22 | | | | |
| M4 + patch | 24 | | | | |
| M5 | 14 | | | | |
| M5.5 | 16 | | | | |
| M6 | 18 | | | | |
| M7 | 22 | | | | |
| M9 | 16 | | | | |
| M10 | 23 | | | | |
| M11 | 12 | | | | |
| M12 | 10 | | | | |
| M13–15 | 9 | | | | |
| **Total** | **220** | | | | |

---

## Test Conventions

**Pass criteria** — The exact expected result is observed. No workarounds needed.  
**Fail criteria** — Anything other than the expected result. Record the actual result.  
**Skip criteria** — Test cannot be run due to environment (e.g. Linux-only test on Windows).  

**Recording bugs:** If a test fails, add a bug note:  
`BUG: <what happened> | FIX ATTEMPT: <what you tried> | RESULT: <resolved/open>`

**Date tested:** Record the date at the top of each file when you run the tests.

---

## Environment Checklist

Before starting, confirm:

- [x] `python assistant.py` starts without errors
- [x] Both API keys are present in `config/settings.json`
- [x] Vault path in `settings.json` points to a real vault
- [x] Obsidian is open with the vault loaded
- [x] You are on the `dev` branch

---

*Save this file to `AI/Tests/00-Test-Index.md` in your vault.*
