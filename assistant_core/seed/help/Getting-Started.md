<!-- help-version: 17 -->
---
tags: [help, user-guide]
---
# Getting Started

Part of [[How-To-Use]]. For install/deployment details see [[Deployment-Guide]].

## Where it runs
The assistant runs as a background service — normally on your always-on **box** (Linux). Your laptop's
Obsidian plugin talks to it over the LAN. Indexing, the knowledge graph, and nightly jobs happen on the
box; the laptop just chats.

## Start the service
```bash
python -m assistant_core            # headless (production) — watcher + HTTP API
python -m assistant_core --terminal # interactive terminal (debug/admin)
```
Stop with `curl http://127.0.0.1:8765/shutdown` or `systemctl restart assistant`.

## Connect the Obsidian plugin
1. Enable **AI Assistant** in Community Plugins.
2. Open its settings (the **⚙** gear in the sidebar header, or Settings → AI Assistant): set **Host**,
   **Port**, and — if the service is on another machine — the **API token** that matches the service's
   `api_token`.
3. Open the sidebar (ribbon icon or command palette → "AI Assistant"). The status line shows **✓
   Connected** (Live mode) or **⚡ Service offline — vault mode** (fallback via the watcher).

## Your first chat
Type a message and **Send**. Try:
- "Summarize the active note." (open a note first)
- `vault:search rocket` — a plain keyword search.
- Turn on **📚 Vault QA** and ask "What do my notes say about X?"

## The three ways to talk to it
| Interface | Best for | How |
|---|---|---|
| **Plugin sidebar** | Everyday live chat | Type + Send; buttons for Selection, Vault QA, Graph, Prompts |
| **Vault watcher** | Async / from your phone | Add `assistant-status: pending` + `assistant-request: <question>` to a note; it writes the answer back |
| **Terminal** | Setup, tests, admin commands | `python -m assistant_core --terminal` |

Next: [[Commands]] and [[Features]].