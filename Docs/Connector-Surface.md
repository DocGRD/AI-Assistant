# Connector Surface

*Status: planning / M46 target. Defines how Loremaster exposes vault tools as a **connector** so external platforms (Grok, Claude, ChatGPT, Gemini, and future MCP clients) can call the same allowlisted tools the Web Partner Protocol uses — on laptop and phone.*

**Related:** [`Web-Partner-Protocol.md`](Web-Partner-Protocol.md) (Path 1 — paste/continue handoff). This document is **Path 2** — Loremaster *is* the tool provider.

---

## Purpose

Web AIs increasingly support **connectors** (MCP, Custom GPT Actions, Claude connectors, Grok connectors, Gemini apps). Rather than only packaging prompts for humans to paste, Loremaster should:

1. Expose a **stable, authenticated tool API** over HTTP (and optionally MCP).
2. Use **one tool contract** shared with the Web Partner Protocol allowlist.
3. Work when the caller is:
   - The Obsidian plugin (existing),
   - A remote connector on Grok/Claude/ChatGPT/Gemini,
   - A phone using a public base URL (Tailscale / Cloudflare Tunnel),
   - Automation on the home Linux box.

Obsidian remains the place for Approvals, Private toggle, and vault UX. Connectors extend **reach**; they do not replace the plugin.

---

## Design principles

| Principle | Rule |
|-----------|------|
| **One contract, many faces** | Agent `vault:*` tools, Web Partner `TOOL_REQUEST`, MCP tools, and OpenAPI actions share names, allowlist, and privacy checks. |
| **Auth required** | No unauthenticated tool access. Bearer token (existing `api_token`) minimum; recommend tunnel + optional IP allowlist. |
| **Capability tiers** | `read` vs `propose` — web/remote callers default to read; writes only stage Approvals. |
| **Phone + laptop** | Same base URL works from mobile apps and desktop; LAN-only is insufficient for phone away from home. |
| **Zero cost ops** | No paid gateway required; self-hosted service + free tunnel options. |
| **Obsidian is source of truth** | Connector-staged proposals appear in the same Approvals inbox as auto-organize/goals. |
| **Prefer official connectors** | Use platform MCP/Actions/Connectors before DOM automation. |

---

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │  Home Linux box (systemd)              │
                    │  Loremaster service                    │
                    │  Existing HTTP API + tool registry     │
                    │  New: /connector/* + optional MCP      │
                    └───────────────────┬────────────────────┘
                                        │
                     auth: Bearer <api_token>
                                        │
          ┌─────────────────────────────┼─────────────────────────────┐
          ▼                             ▼                             ▼
   Obsidian plugin              Remote connectors                 Local MCP
   (laptop / phone)             Grok / Claude / ChatGPT           stdio or
   LAN or base URL              Gemini (as supported)             streamable HTTP
          │
          └──────── Obsidian Sync (vault + Approvals) ────────┘
```

### Base URL

| Environment | Example |
|-------------|---------|
| Laptop on LAN | `http://192.168.x.x:8765` |
| Phone / remote connector | `https://loremaster.<tailnet>.ts.net` or Cloudflare Tunnel URL |
| Localhost only | `http://127.0.0.1:8765` (plugin on same machine) |

Document deploy choices in `Docs/DEPLOYMENT.md` (extend): Tailscale Funnel, Cloudflare Tunnel, reverse proxy + TLS, firewall. **Do not** expose the port to the open internet without token **and** TLS.

---

## Capability tiers

| Tier | Tools | Remote default |
|------|--------|----------------|
| **`connector:read`** | Same allowlist as Web Partner Protocol Phase 1: read, search, list, find, links, ask, query, sources, passage, guide | **On** |
| **`connector:propose`** | Stage create/update/restructure as Approvals items; never apply | Opt-in per token or setting |
| **`connector:admin`** | Provider registry, reindex, shutdown | **Never** for web partners; local plugin only |

Tokens may later carry scopes; v1 can use a global setting: `connector_propose_enabled: false`.

---

## Shared tool contract

Normalize all faces to the same logical tools:

| Name | Args (logical) | Returns |
|------|----------------|---------|
| `vault_read` | `path` | text or error |
| `vault_search` | `query` | hits |
| `vault_list` | `folder?` | listing |
| `vault_find` | `glob` | paths |
| `vault_links` | `note` | note + links |
| `vault_ask` | `question` | answer + citations |
| `vault_query` | `expr` | structured hits |
| `vault_sources` | `claim` | supporting notes |
| `vault_passage` | `ref` | passage guide |
| `vault_guide` | `topic` | graph guide |

Wire names may use dots or slashes per platform (`vault.read` vs `vault_read`); the service normalizes to one internal dispatch table.

**Privacy:** every tool checks note/turn privacy. Without private opt-in (header or param reserved for trusted plugin), private notes are invisible and return a clear error.

**Path jail:** existing `resolve_in_vault` rules; no escape.

---

## HTTP surface (v1 sketch)

Reuse FastAPI app; add a dedicated router prefix so plugin routes and connector routes stay clear.

### Auth

```http
Authorization: Bearer <api_token>
```

Missing/invalid token → `401`. Optional: `X-Loremaster-Client: plugin|connector|mcp` for logging.

### Endpoints (illustrative)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/connector/v1/health` | Liveness + tier flags (no vault data) |
| `GET` | `/connector/v1/tools` | List tools + short schemas (for GPT Actions / MCP discovery) |
| `POST` | `/connector/v1/tools/{tool_name}` | Execute one tool |
| `POST` | `/connector/v1/batch` | Optional: up to N tool calls in one request (cap 3) |

**Execute body (example):**

```json
{
  "args": { "query": "rocket stove" },
  "private_opt_in": false,
  "session_id": "optional-client-correlation"
}
```

**Execute response:**

```json
{
  "ok": true,
  "tool": "vault_search",
  "output": "...",
  "truncated": false,
  "error": null
}
```

Rate-limit connector routes separately from the plugin chat UI (conservative defaults).

### OpenAPI

Publish `/connector/v1/openapi.json` for ChatGPT Custom GPT Actions and similar importers. Keep schemas minimal and stable.

---

## MCP surface (optional wrapper)

Expose the **same** tools via Model Context Protocol for clients that speak MCP (including platforms that add remote MCP connectors).

| Transport | Use case |
|-----------|----------|
| **Streamable HTTP** | Remote Grok/Claude-style connectors pointing at base URL |
| **stdio** | Local desktop agents on the same machine as the service |

Implementation sketch:

- `assistant_core/connector/mcp_server.py` maps MCP tool list → internal dispatch
- Auth: token in header for HTTP transport; stdio only on localhost
- Tool descriptions copied from the shared catalog (short, honest, no write claims)

MCP is a **face**, not a second business-logic stack.

---

## Platform adapters (M47+)

| Platform | Integration path | Notes |
|----------|------------------|--------|
| **Grok** | Custom connector / MCP pointing at `/connector/v1` or MCP HTTP | Align with how Grok expects connector auth and tool schemas; prioritize first if ecosystem is already in use. |
| **Claude** | Connectors / MCP as offered on web or desktop | Same allowlist; user enables connector in Claude settings. |
| **ChatGPT** | Custom GPT Actions via OpenAPI | Import openapi.json; store token as GPT secret. |
| **Gemini** | Apps / extensions / function calling as available on free tier | Prefer official remote tools; avoid scraping. |

Each adapter should be a thin config + docs page, not a fork of tool logic.

**Non-goal:** Playwright/DOM bots as the primary connector path. Optional research only if a platform has zero connector support and still matters.

---

## Obsidian as the browser (Path 3, desktop comfort)

Connectors reduce the need to paste into external tabs. When the user still wants a web UI:

- **Desktop:** optional pane (Custom Frames / Web Viewer) for Gemini/Claude/ChatGPT/Grok beside the Loremaster sidebar — packaging still from Path 1 if the partner has no connector.
- **Phone:** do **not** rely on in-Obsidian webviews. Phone uses plugin + system browser (Path 1) and/or platform apps with connectors (Path 2).

---

## Cross-device behavior

| Scenario | Expected behavior |
|----------|-------------------|
| Laptop + service on LAN | Plugin and local connectors use LAN URL + token. |
| Phone at home (Wi‑Fi) | Plugin uses LAN URL or mDNS if configured. |
| Phone away from home | Plugin and remote connectors use **tunnel base URL** + token. |
| Service down | Plugin Vault mode / watcher; connector calls fail cleanly with 503; no partial vault writes. |
| Proposal from connector | Item appears in Approvals on next plugin open (any device via Sync). |

---

## Privacy & security checklist

- [ ] Token required on all `/connector` and MCP HTTP routes
- [ ] TLS for any non-LAN base URL
- [ ] Private notes excluded unless explicit opt-in mechanism (plugin trusted path only in v1)
- [ ] Propose tier off by default
- [ ] No admin tools on connector surface
- [ ] Logs: client type, tool name, ok/error — not full note bodies at info level
- [ ] Document token rotation in DEPLOYMENT.md

---

## Service modules (suggested)

```
assistant_core/connector/
  __init__.py
  router.py          # FastAPI /connector/v1/*
  auth.py            # bearer validation, optional scopes
  dispatch.py        # name normalize → tool registry (read/propose tiers)
  openapi.py         # generate minimal OpenAPI
  mcp_server.py      # optional MCP face
  limits.py          # rate limits, batch caps, output truncation
```

Share allowlist constants with `assistant_core/web_partner/` (single source of truth module, e.g. `assistant_core/tools/allowlists.py`).

---

## Testing (M46–M49)

- Auth: no token / bad token → 401
- Allowlist: write tool name → 403/error, no side effect
- Privacy: private path without opt-in → safe error
- Batch cap: 4th call rejected
- OpenAPI: importable, actions match tools list
- MCP (if enabled): list tools + call vault_search round-trip
- Mobile: plugin against tunnel URL; connector call from external client against same URL
- Load: rate limiter does not break normal plugin chat

---

## Docs to update when implementing

| Doc | Update |
|-----|--------|
| `Docs/DEPLOYMENT.md` | Tunnel, token, connector base URL, phone setup |
| `Docs/Help/Features.md` / Commands | “Connect external AIs”, security warnings |
| `README.md` | Short “Connector surface” blurb |
| `AI/System/System-Prompt.md` | Local model awareness: external partners may call read tools |

---

## Non-goals

- Replacing the Obsidian plugin with a pure web chat UI
- Training or fine-tuning on vault data
- Exposing the vault as unauthenticated public search
- Full unsupervised multi-agent loops driven solely by remote models without Approvals

---

## Milestone mapping

| Milestone | Deliverable |
|-----------|-------------|
| **M46** | `/connector/v1` health + tools + execute; shared allowlist module; OpenAPI; auth; tests |
| **M47** | First platform adapter (recommend Grok if connector UX is already familiar) + setup doc |
| **M48** | Optional desktop Obsidian webview layout for partners without connectors |
| **M49** | Tunnel deploy notes, mobile test matrix, Help + prompt seeding |

---

## Relationship to Web Partner Protocol

| | Web Partner (Path 1) | Connector Surface (Path 2) |
|--|---------------------|----------------------------|
| **Who runs tools** | Loremaster after user pastes | Loremaster on direct HTTP/MCP call |
| **Who initiates** | User from sidebar | Remote model/platform |
| **Works offline phone** | Via watcher + Sync | Needs reachable base URL |
| **Allowlist** | Same Phase 1 read set | Same |
| **Best when** | Platform has no connector; max privacy control | Platform supports connectors; fewer paste steps |

Implement Path 1 first (universal). Path 2 reuses its allowlist and privacy rules so behavior stays consistent whichever face the user chooses.
