# Plan: Web Partners & Connector Surface

*Status: ready to implement. Owner: DocGRD. Depends on existing agent loop, tool registry, plugin sidebar, vault watcher, and free-tier provider routing.*

**Spec docs (committed):**

- [`Web-Partner-Protocol.md`](Web-Partner-Protocol.md) — Path 1 (paste / continue; phone + laptop)
- [`Connector-Surface.md`](Connector-Surface.md) — Path 2 (HTTP / MCP connector; same allowlist)

This plan turns those specs into ordered milestones, work packages, acceptance checks, and open decisions.

---

## Problem

Loremaster already routes free **API** tiers (Groq, Google AI Studio, Cerebras, NVIDIA) and has a basic web handoff (`vault:research` + `WebUI-Prompt.md`). Leading free **web-portal** models (Gemini, Claude, ChatGPT, Grok) are stronger for many tasks but:

1. Cannot see the vault or run `vault:*` tools.
2. Are awkward to use from the sidebar (copy prompt → browser → paste back, no tool loop).
3. Need to work on **phone and laptop**, with Obsidian as the primary surface (not a Chrome-only extension).
4. Should eventually **be callable as a connector** where platforms support MCP / Actions / Connectors.

## Goal

From the Loremaster sidebar (desktop + mobile):

1. Start a **web partner session** with Gemini / Claude / ChatGPT / Grok.
2. Let that partner **request allowlisted read tools**; Loremaster executes them and continues the loop.
3. Optionally expose the **same tools** over authenticated HTTP/MCP so platforms can call Loremaster directly.
4. Keep zero-cost, privacy routing, propose/commit, and Obsidian-as-KB intact.

## Non-goals

- Paid APIs as a requirement.
- Unsupervised vault writes from web models.
- DOM automation / Playwright as the primary integration.
- Replacing the plugin with a pure web chat UI.
- Merging `WebUI-Prompt.md` with the local system prompt.

---

## Constraints (locked)

| Constraint | Implication |
|------------|-------------|
| Obsidian is the browser | Sidebar + optional desktop webview; no Chrome-extension dependency for the happy path. |
| Phone + laptop | Path 1 works offline via watcher + Sync; Path 2 needs a stable tunnel base URL for remote/phone. |
| Web AIs have connectors | Prefer being a connector (Path 2) where platforms allow it; Path 1 remains universal fallback. |
| Production shape | Linux systemd service + token + Obsidian Sync already in place — extend, don’t fork. |

---

## Architecture (target)

```
Path 1 (universal)          Path 2 (connectors)           Path 3 (desktop comfort)
─────────────────          ──────────────────           ──────────────────────
Sidebar packager    →      /connector/v1 + MCP    →      Optional webview pane
Paste / Continue           Grok / Claude / GPT           beside sidebar
Allowlisted tools          Same allowlist                Still uses Path 1 or 2
Watcher fallback           Tunnel base URL + token       Not required on phone
```

**Single tool contract** shared by:

- Local agent `vault:*` (full set, existing)
- Web partner `TOOL_REQUEST` (read allowlist)
- Connector HTTP / MCP (read allowlist; optional propose tier later)

Suggested shared module: `assistant_core/tools/allowlists.py`.

---

## Milestone plan

### M43 — Web Partner Protocol (service)

**Outcome:** Packager, parser, executor, session persistence; testable without plugin UI.

| Work | Detail |
|------|--------|
| Package layout | `assistant_core/web_partner/` — `packager`, `parser`, `executor`, `session`, `loop` |
| Allowlist module | `tools/allowlists.py` — `WEB_PARTNER_READ` list used by partner + connector |
| Parser | `TOOL_REQUEST` / `FINAL_ANSWER`; tolerant of messy output; max 3 tools/reply |
| Executor | Dispatch to existing tools; path jail; private-note blocking |
| Session | `session_id`, partner, round, `private_opt_in`, `AI/Research/web-partner/...` |
| Caps | Max 5 rounds/session (configurable) |
| CLI / tests | Golden parser cases, allowlist reject, privacy reject, budget truncate |

**Accept when:**

- [ ] Given a synthetic partner reply with tool blocks, tools run and results format correctly.
- [ ] Write-tool names never execute.
- [ ] Private note without opt-in returns safe error.
- [ ] Session folder created under `AI/Research/web-partner/`.

**Estimate:** 2–4 focused days.

---

### M44 — Sidebar: Ask web partner

**Outcome:** End-to-end manual loop in the plugin (desktop + mobile layout).

| Work | Detail |
|------|--------|
| UI | **Ask web partner ▾** — Gemini, Claude, ChatGPT, Grok, Other |
| Actions | Copy package · Open partner URL · Paste response · Run tools / Continue |
| Private | Opt-in checkbox; hard block when Private on and opt-in off |
| Chat thread | Show package summary, tool results, final answer in sidebar |
| HTTP API | Endpoints for package / parse-continue if plugin shouldn’t embed all logic |

**Accept when:**

- [ ] User can complete one full round-trip (question → package → paste → tools → answer) on desktop.
- [ ] Same controls usable on mobile viewport (system browser for partner).
- [ ] No private leakage without opt-in.

**Estimate:** 2–4 days (plugin + small API).

---

### M45 — Multi-round, save, watcher parity

**Outcome:** Daily-driver Path 1.

| Work | Detail |
|------|--------|
| Multi-round | Continue packages include only new tool results + short rolling summary |
| Save | `FINAL_ANSWER` → `final-answer.md` + optional user Save |
| Soft final | No headers → `needs_user_confirm` (Save or nudge Continue) |
| Watcher | Frontmatter path so phone can complete a round when HTTP is down |
| WebUI-Prompt | Seed/update protocol instructions (TOOL_REQUEST / FINAL_ANSWER) |
| Help | Commands / Features notes; episode `ep_handoff` events |
| System prompt | Local model knows when to recommend Ask web partner |

**Accept when:**

- [ ] 3+ round session works without blowing context.
- [ ] Research folder is coherent after Save.
- [ ] Offline phone → online process → result in vault via Sync (one documented path).
- [ ] Help + prompts updated; tests green.

**Estimate:** 2–3 days.

---

### M46 — Connector surface (HTTP + OpenAPI)

**Outcome:** Authenticated `/connector/v1` with the same read allowlist.

| Work | Detail |
|------|--------|
| Routes | `GET health`, `GET tools`, `POST tools/{name}`, optional `POST batch` (cap 3) |
| Auth | Bearer `api_token`; 401 on failure |
| OpenAPI | `/connector/v1/openapi.json` for GPT Actions import |
| Dispatch | Shared allowlist + privacy + path jail |
| Limits | Rate limit connector routes separately from chat |
| Settings | `connector_propose_enabled: false` (stub for later) |
| Tests | Auth, allowlist, privacy, batch cap |

**Accept when:**

- [ ] curl/token can list tools and run `vault_search`.
- [ ] Write tool names rejected.
- [ ] OpenAPI imports cleanly into a Custom GPT Actions draft (manual check).

**Estimate:** 2–3 days.

---

### M47 — First platform adapter (recommend Grok)

**Outcome:** Documented, working connector against one real platform.

| Work | Detail |
|------|--------|
| Prefer Grok | Familiar connector model; align schemas/auth with platform docs |
| Setup doc | `Docs/Connectors-Grok.md` (or section in DEPLOYMENT) — base URL, token, tool list |
| Fallback | Note Path 1 if connector unavailable |
| Optional | Claude connector or ChatGPT Actions if lower friction |

**Accept when:**

- [ ] External platform successfully calls at least `vault_ask` or `vault_search` against the home box.
- [ ] Phone or remote network works via tunnel URL (not only LAN).

**Estimate:** 1–3 days (platform-dependent).

---

### M48 — Desktop Obsidian webview (optional)

**Outcome:** Comfort layout only; not required for mobile.

| Work | Detail |
|------|--------|
| Pane | Custom Frames / Web Viewer for partner site beside sidebar |
| No new protocol | Still Path 1 paste or Path 2 connector |
| Skip if | Connector path already removes friction |

**Accept when:** Side-by-side works on desktop; phone behavior unchanged.

**Estimate:** 1 day or defer.

---

### M49 — Ship hardening

| Work | Detail |
|------|--------|
| DEPLOYMENT.md | Tailscale Funnel / Cloudflare Tunnel, token rotation, phone base URL |
| Mobile test matrix | Plugin LAN, plugin tunnel, watcher fallback, connector remote |
| README | Short “Web partners & connectors” blurb |
| Regression | Full automated suite + one GUI pass on GRDVault |

**Accept when:** Docs match reality; no open P0 privacy holes; suite green.

**Estimate:** 1–2 days.

---

## Suggested implementation order

```
M43 ──► M44 ──► M45 ──► M46 ──► M47 ──► M49
                              └──► M48 (optional, parallel with M47/M49)
```

Do **not** start M46 before the allowlist module exists (M43). Path 1 ships value on phone without tunnels; Path 2 needs M46+deploy.

---

## Shared allowlist (Phase 1 — both paths)

| Allowed | Forbidden |
|---------|-----------|
| `vault:read`, `vault:search`, `vault:list`, `vault:find`, `vault:links` | create / update / copy / move / trash / mkdir |
| `vault:ask`, `vault:query`, `vault:sources` | ingest / ocr / transcribe / webresearch |
| `vault:passage`, `vault:guide` | `command:run`, scripts, admin, provider registry |

Writes only via Approvals later (`connector:propose` / partner suggestion → staged card).

---

## Privacy rules (both paths)

1. Default: private notes never leave the machine and never appear in packages or connector results.
2. Explicit per-handoff opt-in required for private context in Path 1.
3. Connector v1: no private opt-in from untrusted remote clients (plugin trusted path only if needed).
4. Never package API keys, settings secrets, or raw episode dumps.
5. TLS required for any non-LAN base URL.

---

## Files likely touched

| Area | Paths |
|------|--------|
| Service | `assistant_core/web_partner/*`, `assistant_core/connector/*`, `assistant_core/tools/allowlists.py`, `server/` routes |
| Prompts | `AI/System/WebUI-Prompt.md` (seed), system prompt seed, Help notes |
| Plugin | ChatView / actions menu, new partner panel or modal, mobile layout |
| Docs | This plan, protocol specs, DEPLOYMENT, README, Help |
| Tests | `tests/test_web_partner_*.py`, `tests/test_connector_*.py` |

---

## Open decisions (resolve during M43–M45)

1. **Package size budget** — default 12–16k token-equivalent; confirm on real vault notes.
2. **Soft FINAL_ANSWER** — auto-save vs require explicit Save.
3. **Partner presets** — whether `AI/System/Web-Partners.md` is needed in M44 or later.
4. **Watcher frontmatter schema** — exact keys for partner paste/continue without breaking existing pending requests.
5. **M47 platform** — lock Grok vs Claude vs ChatGPT after a one-hour feasibility check each.
6. **MCP in M46 or later** — HTTP+OpenAPI first is enough for GPT Actions; add MCP when a target platform requires it.

---

## Success criteria (program level)

- [ ] On **laptop**: sidebar web partner multi-round session with real vault tool results; optional connector call from one external platform.
- [ ] On **phone**: same Path 1 flow via system browser; service reachable via tunnel **or** watcher fallback completes a session.
- [ ] Private notes never appear in a web package or connector response without explicit rules above.
- [ ] Zero new paid subscriptions required.
- [ ] Protocol + connector docs match implemented behavior.

---

## Risk register

| Risk | Mitigation |
|------|------------|
| Web models ignore TOOL_REQUEST schema | Strong WebUI-Prompt examples; tolerant parser; soft-final fallback |
| Context too large | Aggressive truncation; titles-first; rolling summary on Continue |
| Token leaked on public tunnel | TLS + bearer; rotation docs; optional IP allowlist |
| Platform connector APIs change | Thin adapters; Path 1 always works |
| Scope creep into browser automation | Explicit non-goal; reject in review |
| Mobile plugin UI too cramped | Minimal controls first; paste box + Continue only on small screens |

---

## Resume checklist

When picking this up:

1. Read this plan + `Web-Partner-Protocol.md` + `Connector-Surface.md`.
2. Implement shared `allowlists.py` and M43 modules first.
3. Wire plugin only after parser/executor tests pass.
4. Deploy tunnel before promising phone connector or remote Grok/Claude tools.
5. Update `Project-State.md` status line when each milestone merges.

---

*End of plan. Spec details and wire formats live in the linked protocol docs; this file is the execution roadmap.*
