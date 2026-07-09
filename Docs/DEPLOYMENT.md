# Deployment & Test Guide

*Zero-Cost AI Operating System for Obsidian (plugin "Loremaster") — v1.9 (Milestones 1–40). Last updated: 2026-07-09.*

> **Updating a running box to a new release.** SSH in, then:
> `cd ~/AI-Assistant && git fetch origin && git reset --hard <tag>` (e.g. `v1.9.0`), then restart **without
> sudo** via the in-app endpoint: `curl -s -X POST -H "X-API-Key: <token>" http://<box>:8765/restart`
> (there's no passwordless sudo on the box — use `/restart`, not `systemctl`). Plugin updates go through
> **BRAT** (`DocGRD/AI-Assistant`); keep the plugin and the service on the same release. Never force-push a
> published tag — cut a new patch tag for a post-release fix.
>
> **New config since v1.0** (all optional, code-default-safe): `write_guard` (`off|flag|source`, default
> `flag` — M37 trust-on-write), `hallucination_guard` (`escalate_web`), `link_validation` (`strip`),
> `auto_briefing_enabled` / `auto_organize_enabled` / `auto_consolidate_enabled` + their `*_hour`,
> `background_hourly_budget`, `goals_enabled`. `vault:analytics` is index-based and runs in ~7s even on a
> 2k-note vault.

How to deploy the assistant and verify **every** milestone. For day-to-day usage see
[User-Guide](User-Guide.md); for architecture see [Project-State](Project-State.md). A production
end-to-end deployment (Linux box + GPU embeddings + LAN plugin) is covered in full below, including the
gotchas found bringing it up.

---

## 0. Topology

| Machine | Role | Settings |
|---|---|---|
| **Linux box** (always-on, NVIDIA GPU) | Production: watcher + HTTP API + **Vault QA indexing** | `host: 0.0.0.0`, `api_token`, `index_on_startup: true`, `embedding_device: cuda` |
| **Windows laptop** | Development / occasional use | localhost; **does not index** (`index_on_startup: false`) |
| **Phone / other devices** | Via Obsidian + the watcher, or the plugin pointed at the box | — |

Obsidian Sync keeps the vault identical everywhere; the **vector index is per-machine** (under `data/`,
git-ignored) and is **not** synced.

---

## 1. Install

**One-command installers** (recommended):

```powershell
# Windows (PowerShell) — from the repo root
./install/install.ps1
```
```bash
# Linux — from the repo root
./install/install.sh            # add --service to also set up the systemd unit
                                # add --gpu     to install the CUDA-12 embedding stack
```
They create `.venv`, install `requirements.txt`, and copy `settings.example.json` → `settings.json`
(only if missing). Then edit `settings.json` (§2).

**Manual install** (equivalent):

```bash
git clone https://github.com/DocGRD/AI-Assistant.git
cd AI-Assistant
python -m venv .venv                 # Python 3.12+ (box runs 3.12, laptop 3.13)
.venv\Scripts\Activate.ps1           # Windows  (Linux: source .venv/bin/activate)
python -m pip install -r requirements.txt
```
- If `pip` ever fails with a launcher error after a move/rename, use `python -m pip …` (the `.exe`
  shims embed an absolute path).
- **Optional feature deps** (graceful without them): `pip install pypdf` (PDF ingest, M22) and
  `pip install faster-whisper` (audio transcription, M27 — GPU-capable on a CUDA box).

### GPU embeddings (production box) — the exact recipe

Local embeddings run on CPU by default. On an NVIDIA box they can run on the GPU — much faster for the
one-time full index build. **Version-pin matters:** the latest `onnxruntime-gpu` targets CUDA 13; pin the
**CUDA-12** build to match a typical driver (535 = CUDA 12.2):

```bash
.venv/bin/pip uninstall -y fastembed onnxruntime
.venv/bin/pip install "fastembed-gpu" "onnxruntime-gpu==1.22.0" \
                      "nvidia-cudnn-cu12" "nvidia-cublas-cu12" "nvidia-cuda-runtime-cu12"
```
Then set `embedding_device: cuda`. No system CUDA/cuDNN install or `LD_LIBRARY_PATH` is needed — the
embedder calls `onnxruntime.preload_dlls()` to load the CUDA libs from the `nvidia-*-cu12` pip packages.
Verify: `python -c "import onnxruntime as o; print(o.get_available_providers())"` should list
`CUDAExecutionProvider`.

**First index build downloads the embedding model (~130 MB) once.** If the download stalls (some networks
break HuggingFace's *Xet* transfer — connections sit in `CLOSE-WAIT`), force the classic HTTPS path:
```bash
HF_HUB_DISABLE_XET=1 .venv/bin/python -c "from fastembed import TextEmbedding; \
  TextEmbedding('BAAI/bge-small-en-v1.5')"   # caches the model; the service then loads it offline
```

## 2. Configure (`assistant_core/config/settings.json`)

Copy `assistant_core/config/settings.example.json` → `assistant_core/config/settings.json` and fill in.
**Never commit real keys** — `settings.json` is git-ignored. (The loader also falls back to a repo-root
`config/settings.json` if the package one is missing — pre-reorg installs keep it there; keep only one, or
keep both identical.) Every key in the example is optional except `vault_path` and at least one provider
key — missing keys fall back to code defaults, so a minimal file works.

| Key | Box | Laptop |
|---|---|---|
| `vault_path` | path to the vault | path to the vault |
| `groq_api_key`, `google_api_key`, `cerebras_api_key` | real keys | real keys |
| `provider_source_url` | (optional) source for `vault:update-providers` | — |
| `host` / `port` | `0.0.0.0` / `8765` | `127.0.0.1` / `8765` |
| `api_token` | a strong secret | (match the box's, in the plugin) |
| `index_on_startup` | `true` | `false` |
| `embedding_device` | `cuda` | `cpu` |
| `embedding_threads` | optional CPU cap | optional |

## 3. First run

```bash
python -m assistant_core --terminal   # or: python -m assistant_core  (headless)
```
On first run it seeds the vault: `System-Prompt.md`, `WebUI-Prompt.md`, `Provider-Registry.md`,
`AI/Prompts/` (examples), `AI/Scripts/` (+ `proposed/` + README), memory templates. The startup report
prints the provider table + Vault-QA index status. On the box, the index builds (`vault:reindex` to
rebuild manually; `vault:reindex full` for a clean rebuild).

## 4. Run as a service (Linux box)

`install/install.sh --service` writes `/etc/systemd/system/assistant.service` (needs sudo): `Type=simple`,
`Restart=always`, `WorkingDirectory` = repo root, `ExecStart` = `.venv/bin/python assistant.py`, logs to
`logs/service.log`. Headless is automatic (no TTY). Enable + start:
```bash
sudo systemctl enable --now assistant
```
- **Restart cleanly:** `sudo systemctl restart assistant`, or (no sudo) `curl http://127.0.0.1:8765/shutdown`
  — `Restart=always` relaunches it.
- **Gotcha:** `pkill -f assistant.py` can miss the process and leave a *stale* instance serving old code
  (and holding the port). Prefer `sudo systemctl restart assistant`, or kill by the full venv path:
  `pkill -9 -f "AI-Assistant/.venv/bin/python"`.
- With `index_on_startup: true`, the **first** startup builds the whole index (slow on an old CPU, seconds
  on GPU) and blocks the HTTP API until done; **later** startups just load the persisted index (fast) and
  only re-embed changed notes. On a slow-CPU box, either build once out-of-band or use GPU.

## 4a. Background maintenance (automatic)

The headless service runs a `MaintenanceScheduler` thread — no OS cron needed:

- **Weekly provider discovery** (~03:00) → writes `AI/System/Provider-Registry-proposed.md`. Review, then
  `vault:update-providers apply`. Gated by `auto_discovery_enabled` / `auto_discovery_interval_days` / `auto_discovery_hour`.
- **Nightly memory consolidation / "dreaming"** (~04:00) → reads new episodes and writes a proposal to
  `AI/Memory/proposed/consolidation-YYYY-MM-DD.md` (durable-fact candidates, **forced-private** extraction,
  deduped against `Learned-Facts`). Live memory is never changed; copy accepted facts into `Learned-Facts`.
  Gated by `auto_consolidate_enabled` / `auto_consolidate_hour`.

- **Knowledge graph** (M18, same nightly window, **opt-in**) → extracts entities/relations from changed
  notes into `AI/Graph/Entities/` (browsable in Obsidian's graph view). Off by default — enable with
  `auto_graph_enabled: true` (highest-cost job); `graph_build_limit` caps notes per run.

Both consolidation and graph are **propose/commit or derived** (never edit your notes). To run by hand
(or from your own cron / Task Scheduler instead of the in-process thread):

```
python -m assistant_core --consolidate          # write a consolidation proposal
python -m assistant_core --consolidate --apply   # also merge new facts into Learned-Facts
python -m assistant_core --build-graph [--limit N]   # build the knowledge graph incrementally
```

`vault:graph <note>` (terminal or plugin) extracts one note on demand; the plugin's **Graph** button
opens the subgraph viewer.

**Web research (M21).** `vault:webresearch <question>` (terminal or plugin) searches the web, fetches the
top pages, writes a cited synthesis + the verbatim sources under `AI/Research/<date>-<slug>/`. Search is
**keyless** (DuckDuckGo) by default — set `tavily_api_key` for a more reliable API, and optionally
`pip install trafilatura` for better page extraction. **Privacy:** a `private` turn is blocked from the
web entirely; only the query string ever leaves the machine. Gated by `web_research_enabled` (default
true); `web_max_results` / `web_max_fetches` bound the cost. The manual `vault:research` paste round-trip
remains as a fallback.

`vault:discover-providers` (terminal or plugin) triggers discovery on demand. Sample crontab (if you
prefer OS scheduling — set `auto_consolidate_enabled: false` to avoid double runs):
`0 4 * * *  cd /path/to/repo && python -m assistant_core --consolidate`.

## 5. LAN access (use the box from the laptop)

1. Box: `host: 0.0.0.0` + a strong `api_token`; restart.
2. **Firewall:** if `ufw` is active it blocks the port even on the LAN. Allow it (scoped to your subnet):
   ```bash
   sudo ufw allow from 192.168.0.0/16 to any port 8765 proto tcp   # or your exact /24
   ```
3. Laptop plugin → **⚙ Settings** → Host = box LAN IP, Port = `8765`, **API token** = the same secret.
   The badge turns green when connected.

Notes: the auth header is **`X-API-Key`** (the plugin sends it automatically). Without a token the API is
open to anyone who can reach the port — always set one when `host` is `0.0.0.0`. The laptop plugin drives
the **box** service, so provider keys, web-search keys, and the index all live on the **box**, not the
laptop. Quick check from the laptop: `curl http://<box-ip>:8765/status -H "X-API-Key: <token>"`.

## 6. Obsidian plugin

Build + deploy to the vault, then reload it in Obsidian (Community Plugins → toggle off/on):
```bash
cd obsidian-plugin && npm install && npm run build
cp main.js styles.css manifest.json "<vault>/.obsidian/plugins/ai-assistant/"
```

---

## 6b. Troubleshooting — lessons from the production box bring-up

Real issues hit deploying to a Linux box (Ubuntu, GTX 1650 SUPER, driver 535 / CUDA 12.2), and their fixes:

| Symptom | Cause | Fix |
|---|---|---|
| Service crash-loops on start (`FileNotFoundError: settings.json`) | Config kept at repo-root `config/settings.json` (pre-reorg), loader looked only in the package dir | Loader now falls back to `config/settings.json`; or copy it into `assistant_core/config/`. |
| A code change "won't take" after restart | `pkill -f assistant.py` missed a stale process still holding the port | `sudo systemctl restart assistant` or `pkill -9 -f "AI-Assistant/.venv/bin/python"` |
| Startup hangs at "Downloading embedding model", connections in `CLOSE-WAIT` | HuggingFace **Xet** transfer stalls on some networks | Pre-fetch with `HF_HUB_DISABLE_XET=1` (see §1), then the service loads it offline |
| `import onnxruntime` → `libcudart.so.13: cannot open` | Latest `onnxruntime-gpu` is built for CUDA **13**; box has CUDA 12 | Pin `onnxruntime-gpu==1.22.0` (CUDA-12 build) — see §1 GPU recipe |
| GPU never used under systemd (falls back to CPU) | onnxruntime can't find cuDNN/cuBLAS (no system install, no `LD_LIBRARY_PATH`) | The embedder calls `onnxruntime.preload_dlls()` to load them from the `nvidia-*-cu12` pip packages — just install those |
| First index build takes many minutes and blocks the API | On an old CPU the indexing loop is the bottleneck; `index_on_startup: true` blocks HTTP until done | Use GPU embeddings, or build once out-of-band; later startups just load the persisted index (fast) |
| Laptop can't reach the box on 8765 (SSH works) | `ufw` allows 22 but blocks 8765 | `sudo ufw allow from <subnet> to any port 8765 proto tcp` (§5) |
| Every reply becomes a **web handoff** | Request too large — a huge active note (e.g. an Excalidraw `.excalidraw.md`, ~140k tokens of JSON) was injected whole and exceeded every provider | Fixed: injected note context is capped (~12k chars) and raw Excalidraw is skipped. Also check providers aren't daily-rate-limited. |
| Reply contains raw `vault:list …` text | A weak fallback model (used when better providers are rate-limited) emitted malformed inline commands | Fixed: the loop strips command-spam and shows a graceful fallback |

---

## 7. Testing

**Run the entire automated suite (302 tests):**
```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"   # Windows
.venv/bin/python -m unittest discover -s tests -p "test_*.py"                                  # Linux
```
The assistant can also self-test from the terminal or plugin: **`vault:test`**.

Milestones **17–29** are each covered by a dedicated test module (`test_consolidation`, `test_graph`,
`test_ocr`/`test_excalidraw`, `test_task_ledger`/`test_research_roundtrip`, `test_web`, `test_ingest`,
`test_scripture`, `test_provenance`, `test_query`, `test_audio`, `test_study`, plus `test_agent_loop` for
M29) and a manual acceptance doc under `AI/Tests/` (see `AI/Tests/00-Test-Index.md`). The GUI is exercised
by `test_gui_harness` + the desktop-automation runbook (`Docs/Tests/GUI-Automation-Runbook.md`).

**Coverage at a glance:** Milestones **1–3** are manual acceptance docs only (startup, providers,
vault tools — they predate the suite). **M4–M8** now have automated coverage for their deterministic
parts (routing, memory/episodes/context, research tools, watcher parsing/chunking, server endpoints,
web-handoff packaging + headless) with a manual remainder for LLM-behaviour/UI. **M9+** have automated
unit tests plus acceptance docs. Every milestone below lists how to run its checks.

| MS | Automated test command (from repo root, venv active) | Manual acceptance doc |
|---|---|---|
| 1 | — (manual) | `AI/Tests/M1-Foundation-Tests.md` |
| 2 | — (manual) | `AI/Tests/M2-Provider-Tests.md` |
| 3 | — (manual) | `AI/Tests/M3-Vault-Access-Tests.md` |
| 4 | `unittest tests.test_routing tests.test_memory_episodes` | `AI/Tests/M4-Router-Memory-Tests.md` |
| 5 | `unittest tests.test_research` | `AI/Tests/M5-Research-Tests.md` |
| 5.5 | `unittest tests.test_watcher` | `AI/Tests/M5-5-Watcher-Tests.md` |
| 6 | `unittest tests.test_server_endpoints` (+ /chat in `tests.test_chat_context`) | `AI/Tests/M6-Plugin-Tests.md` |
| 7 | `unittest tests.test_handoff` | `AI/Tests/M7-Handoff-Tests.md` |
| 7.5 | `unittest tests.test_agent_loop` (agent loop hardening) | `AI/Tests/M7-5-Hardening-Tests.md` |
| 8 | `unittest tests.test_handoff` (3-prompt separation + headless) | `AI/Tests/E2E-Scenario-Tests.md` |
| 9 | `unittest tests.test_editing tests.test_chat_context.ChatContextInjectionTests tests.test_chat_context.EditFlowTests` | `M9-Editing-Tests.md` |
| 10 | `unittest tests.test_routing tests.test_registry_loader` | `M10-Provider-Routing-Tests.md` |
| 11 | `unittest tests.test_rag tests.test_chat_context.VaultQAServerTests tests.test_chat_context.ApiTokenTests` | `M11-VaultQA-Tests.md` |
| 12 | `unittest tests.test_chat_context.MentionsTests tests.test_chat_context.RelevantEndpointTests tests.test_rag.RagServiceTests tests.test_rag.RetrieverQATests` | `M12-Context-Tests.md` |
| 13 | `unittest tests.test_memory` | `M13-14-Quick-Project-Tests.md` |
| 14 | `unittest tests.test_chat_context.MentionsTests.test_project_memory_injected` | `M13-14-Quick-Project-Tests.md` |
| 15 | `unittest tests.test_scripts_runner` | `M13-14-Quick-Project-Tests.md` (§4) |
| 16 | `unittest tests.test_rag.HybridRetrievalTests` | `M16-Hybrid-Retrieval-Tests.md` |
| 16.5 | `unittest tests.test_agent_loop tests.test_chat_context.SettingsApiTests` | (manual: §M16.5 control panel) |

> Prefix every command with `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m` (Windows). Test files
> are shared (e.g. `test_chat_context.py` spans M9/M11/M12/M14), which is why the per-milestone commands
> target specific `TestCase` classes.

---

## Per-milestone sections

### M1 — Foundation / Config / Logging
Startup, `assistant_core/config/settings.json` loading, daily-rotating logs, startup diagnostics.
**Test:** `python -m assistant_core --terminal` → confirm the startup check (`✓ Config Loaded`, `✓ Logs
Ready`). Walk `AI/Tests/M1-Foundation-Tests.md`. **Deploy:** ensure `logs/` is writable.

### M2 — Provider Layer
Groq + Google (now also Cerebras via M10). **Test:** `/use groq` / `/use google` and ask a question;
`AI/Tests/M2-Provider-Tests.md`. *(Note: that doc's `/use` option list predates Cerebras — `cerebras`
is now a valid option.)*

### M3 — Vault Access
`vault:read|search|list|links`, `verbose on/off`. **Test:** `AI/Tests/M3-Vault-Access-Tests.md`.

### M4 — Router + Memory
Token-aware routing, `User-Profile`/`Learned-Facts`, context trimming, episode logs. **Test:**
`AI/Tests/M4-Router-Memory-Tests.md` (`remember:`, `context`, `models`).

### M5 — Research Workflow
`vault:research | import | summarise`. **Test:** `AI/Tests/M5-Research-Tests.md`.

### M5.5 — Vault Watcher
Frontmatter triggers (`assistant-status: pending`), chunking. **Test:** `AI/Tests/M5-5-Watcher-Tests.md`.

### M6 — Obsidian Plugin + HTTP server
`/chat`, `/status`, `/history`, vault-mode fallback. **Test:** `AI/Tests/M6-Plugin-Tests.md`. **Deploy:**
build + copy the plugin (§6 above); reload in Obsidian.

### M7 / M7.5 — Web Handoff + Hardening
Universal web handoff, provider override, history lock; the 8 hardening bug-fixes (headless, agent loop,
log rotation, venv check…). **Test:** `M7-Handoff-Tests.md`, `M7-5-Hardening-Tests.md`.

### M8 — Three-Prompt Architecture + Headless Default  ⚠ no dedicated test doc
System / WebUI / memory prompts kept separate; headless is the default; `/chat/handoff-return` executes
plain-English vault suggestions. **Test (smoke):** start headless (`python -m assistant_core`) → it stays
up with no TTY; `curl /status` works; `curl /shutdown` exits cleanly. Also covered indirectly by the M9+
context-injection tests (same injection path) and `AI/Tests/E2E-Scenario-Tests.md`.
**Gap:** consider adding an `M8` acceptance doc.

### M9 — Context-Aware Editing (propose/commit)
**Automated:** `tests.test_editing` (helpers + watcher staging) and
`tests.test_chat_context.ChatContextInjectionTests` (selection/active-note injection) +
`.EditFlowTests` (proposal, word options, exhaustion→handoff). **Manual:** `M9-Editing-Tests.md`.

### M10 — Provider Registry + Privacy/Task Routing + Health
**Automated:** `tests.test_routing` (privacy filter, task shape, candidates-never-chosen, health flip,
≥3 floor) + `tests.test_registry_loader` (parse, bad-row skip, sentinel, missing file). **Manual:**
`M10-Provider-Routing-Tests.md` (incl. live Groq/Google/Cerebras).

### M11 — Vault QA (local RAG)
**Automated:** `tests.test_rag` (chunker, vector store, indexer, retriever/QA privacy) +
`tests.test_chat_context.VaultQAServerTests` (server QA path + sources) + `.ApiTokenTests` (LAN auth).
**Manual:** `M11-VaultQA-Tests.md` (indexing + cited answers on the box). **Deploy:** indexing is
box-only; first `vault:reindex` downloads the model.

### M12 — Context UX (`@`-mentions, Related, scoped QA)
**Automated:** `tests.test_chat_context.MentionsTests` + `.RelevantEndpointTests`,
`tests.test_rag.RagServiceTests` (relevant-notes, scoped) + `.RetrieverQATests`. **Manual:**
`M12-Context-Tests.md`.

### M13 — Quick Commands + Prompt Library
**Automated:** `tests.test_memory` (`seed_prompts`: seeds when empty, never clobbers). **Manual:**
`M13-14-Quick-Project-Tests.md` §2 (quick bar, Prompts… picker, command palette). **Deploy:** `AI/Prompts/`
seeds on first run.

### M14 — Project Awareness
**Automated:** `tests.test_chat_context.MentionsTests.test_project_memory_injected`. **Manual:**
`M13-14-Quick-Project-Tests.md` §3 (`project:` frontmatter → injects `AI/Memory/Projects/<name>.md`).

### M15 — Self-Testing + Muscle-Memory Scripts (propose/commit)
**Automated:** `tests.test_scripts_runner` (name allow-list / no traversal; refuses unapproved
`proposed/` scripts; runs an approved one; reports nonzero exit). **Manual:**
`M13-14-Quick-Project-Tests.md` §4 (`vault:test`; propose→approve→`vault:run-script`).

### M16 — Hybrid (Graph-Aware) Retrieval
Vault QA blends the M11 vector index with the vault's `[[links]]` + `#tags` (zero new cost). Sources
surfaced via the graph are tagged `(graph)` in the terminal and a dashed **· graph** chip in the plugin.
Tunable via `settings.json` (`hybrid_retrieval`, `hybrid_weights`).
**Automated:** `tests.test_rag.HybridRetrievalTests`. **Manual:** `M16-Hybrid-Retrieval-Tests.md`.
**Deploy:** the index manifest is **SCHEMA 3** — run `vault:reindex` once on the indexing host so the
link/tag graph is captured (the store rebuilds automatically on the schema bump).

### M16.5 — Runtime Config + Plugin Control Panel
Edit the running service's `settings.json` from **Obsidian → Settings → AI Assistant → Service settings**:
**Load** pulls the live config, you edit (toggles / numbers / `hybrid_weights` / write-only secrets,
each tagged *(live)* or *(restart)*), **Save** writes it, and **Restart service** bounces the process.
New settings: `max_agent_steps` (agent iteration cap, was a hardcoded 10), `hybrid_depth` (link-graph
hops). API: `GET/PUT /settings`, `POST /restart`.
**Security:** these admin actions are **refused when the bind is public (`0.0.0.0`) without an
`api_token`** — set a token whenever the API is on the LAN. Secrets are redacted on read and only
overwritten when you type a new value.
**Automated:** `tests.test_agent_loop`, `tests.test_chat_context.SettingsApiTests`.

---

## What to watch (gaps & notes)

- **M1–M3 are manual-only.** They predate the test suite (startup/config, providers, vault read tools);
  verify via the `AI/Tests/` docs + a terminal smoke run. M4–M8 are now largely automated; their docs
  carry an "Automated coverage" header pointing at the test modules, with a manual remainder for
  LLM-behaviour and UI (e.g. the Obsidian plugin, hard-kill crash test, web-AI round-trips).
- **M8 has no dedicated acceptance doc** (covered by E2E + the smoke above) — worth adding.
- **Minor doc drift:** `M2-Provider-Tests.md`'s `/use` option list predates Cerebras.
- **Index is per-machine, not synced** — each machine that serves Vault QA builds its own under `data/`.
  The laptop should *not* index (CPU); point its plugin at the box instead.
- **Model download** happens on the first embedding call on each indexing machine (one-time, then offline).
- **Reload the plugin** in Obsidian after copying a new `main.js` — Obsidian caches it.
- **Secrets:** `assistant_core/config/settings.json` is git-ignored and was scrubbed from history; rotate
  any key that was ever committed. Use an `api_token` whenever the API binds to `0.0.0.0`.
