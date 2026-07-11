"""
Obsidian command-palette catalog — awareness + propose-to-run (M41).

Obsidian commands (core *and* every community plugin the user installs) can only be
*executed* inside the plugin — they call `app.commands.executeCommandById()` in the
Obsidian renderer, which the Python service cannot reach. So the service keeps an
*awareness* copy of the catalog, pushed by the plugin whenever it changes (e.g. a new
plugin is installed), and lets the model:

  • `command:search <query>`  — discover matching commands (read-only lookup)
  • `command:list [plugin]`   — browse the catalog / a plugin's commands
  • `command:run <id|name>`   — PROPOSE running one (never auto-runs)

`command:run` never executes here — it stages a proposal the plugin renders with
Approve / Reject; on approval the plugin executes it and reports the result back. This
mirrors the M29 restructuring flow: powerful, possibly-destructive actions are always
human-approved.

The catalog is stored per-service (outside the vault) because the installed plugin set
is per-device, not per-vault — syncing it through the vault would be wrong.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("assistant")

# Per-service state, outside the vault (device-specific plugin set). Sits beside logs/.
_STATE_PATH = Path(__file__).resolve().parents[1] / "state" / "commands.json"
_lock = threading.Lock()

# Command ids/names whose effect is destructive or outward-facing — the approval card
# shows a ⚠ warning. Everything still requires approval; this only flags the scary ones.
_RISKY = re.compile(
    r"(delete|trash|remove|erase|purge|clear-|reset|uninstall|"
    r"disable-plugin|publish|sync\b|logout|revoke)",
    re.IGNORECASE,
)

# Loremaster's own plugin id — filtered out so the model can't recurse into itself.
_SELF_PLUGIN = "loremaster"


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _load() -> dict:
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"commands": [], "plugins": [], "hash": "", "synced_at": ""}


def replace(commands: list[dict], plugins: list[str] | None = None, hash_: str = "",
            plugin_descriptions: dict | None = None) -> int:
    """Persist the full catalog the plugin just pushed. Returns the stored command count."""
    clean: list[dict] = []
    seen: set[str] = set()
    for c in commands or []:
        cid = str(c.get("id", "")).strip()
        if not cid or cid in seen:
            continue
        source = str(c.get("source", "")).strip()
        if source == _SELF_PLUGIN or cid.startswith(_SELF_PLUGIN + ":"):
            continue
        seen.add(cid)
        clean.append({
            "id": cid,
            "name": str(c.get("name", "")).strip() or cid,
            "source": source,
        })
    kept_plugins = sorted({p for p in (plugins or []) if p and p != _SELF_PLUGIN})
    descs = {k: str(v).strip() for k, v in (plugin_descriptions or {}).items()
             if k in kept_plugins and str(v).strip()}
    data = {
        "commands": clean,
        "plugins": kept_plugins,
        "plugin_descriptions": descs,
        "hash": hash_,
        "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with _lock:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    logger.info(f"[Commands] Catalog synced: {len(clean)} commands, {len(data['plugins'])} plugins")
    return len(clean)


def current_hash() -> str:
    return _load().get("hash", "")


def all_commands() -> list[dict]:
    return _load().get("commands", [])


def plugin_sources() -> list[str]:
    return _load().get("plugins", [])


def plugin_descriptions() -> dict:
    return _load().get("plugin_descriptions", {})


def count() -> int:
    return len(all_commands())


def is_risky(cid: str, name: str = "") -> bool:
    return bool(_RISKY.search(cid or "") or _RISKY.search(name or ""))


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[\s:_/\-]+", s.lower()) if t]


def _score(query: str, cmd: dict) -> float:
    """Cheap, dependency-free fuzzy score of `query` against a command's name + id."""
    q = (query or "").lower().strip()
    if not q:
        return 0.0
    name = cmd["name"].lower()
    cid = cmd["id"].lower()
    if q == name or q == cid:
        return 1000.0

    score = 0.0
    if q in name:
        score += 120.0 - name.index(q)          # earlier substring in the name = stronger
    if q in cid:
        score += 70.0 - min(cid.index(q), 60)

    q_toks = _tokens(q)
    hay_toks = set(_tokens(name)) | set(_tokens(cid))
    hits = sum(1 for t in q_toks if t in hay_toks)
    score += hits * 30.0
    # every query token present somewhere is a strong all-words-match signal
    if q_toks and hits == len(q_toks):
        score += 40.0
    return score


def search(query: str, limit: int = 8) -> list[dict]:
    scored = [(s, c) for c in all_commands() if (s := _score(query, c)) > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _, c in scored[:limit]]


def resolve_exact(target: str) -> dict | None:
    """Resolve ONLY by exact id or exact (case-insensitive) name — no fuzzy guessing.
    Used for `command:run`: we never auto-run a loosely-matched command."""
    target = (target or "").strip()
    if not target:
        return None
    low = target.lower()
    for c in all_commands():
        if c["id"] == target or c["name"].lower() == low:
            return c
    return None


def resolve(target: str) -> dict | None:
    """Resolve an id or a (case-insensitive) name to a catalog entry; fall back to best fuzzy.
    For discovery/lookup — NOT for deciding what to run (see resolve_exact)."""
    return resolve_exact(target) or (search(target, limit=1) or [None])[0]


# ---------------------------------------------------------------------------
# Awareness summary + proposal building
# ---------------------------------------------------------------------------

def summary(max_plugins: int = 24) -> str:
    """One-line awareness string injected into the model's context (empty if no catalog yet)."""
    cmds = all_commands()
    if not cmds:
        return ""
    pl = plugin_sources()
    plug_str = ", ".join(pl[:max_plugins]) + ("…" if len(pl) > max_plugins else "") if pl else "core app only"
    return (
        f"Obsidian command palette: {len(cmds)} commands available (sources: {plug_str}). "
        f"Find one with `command:search <query>`, then `command:run <id>` to propose running "
        f"it (the user approves before it executes). New plugins the user installs appear here "
        f"automatically."
    )


def make_proposal(target: str) -> dict | None:
    """Build a `command_run` approval proposal from an EXACT id or name, or None. Exact-only
    so a vague `command:run` never runs the wrong command — the caller offers candidates."""
    cmd = resolve_exact(target)
    if not cmd:
        return None
    risky = is_risky(cmd["id"], cmd["name"])
    return {
        "kind": "command_run",
        "id": f"cmd-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        "command_id": cmd["id"],
        "name": cmd["name"],
        "source": cmd.get("source", ""),
        "risky": risky,
        "summary": f"Run Obsidian command: {cmd['name']}",
    }


# ---------------------------------------------------------------------------
# Unified handler (used by both the server intercept and the agent loop)
# ---------------------------------------------------------------------------

def _format_hits(hits: list[dict]) -> str:
    if not hits:
        return "No matching Obsidian commands. Try `command:list` to see what's available, " \
               "or a different search term."
    lines = [f"- **{c['name']}** — `{c['id']}`" + (f"  _({c['source']})_" if c.get("source") else "")
             for c in hits]
    return "\n".join(lines)


def handle(prefix: str, arg: str) -> dict:
    """
    Run one `command:` directive.

    Returns a dict with:
      • output   — human/agent-readable text to show or feed back to the model
      • proposal — a command_run proposal (only for `command:run`), else None
    """
    prefix = prefix.lower().strip()
    arg = (arg or "").strip()

    if prefix == "command:search":
        if not arg:
            return {"output": "Usage: `command:search <query>` — e.g. `command:search daily note`.",
                    "proposal": None}
        hits = search(arg, limit=8)
        return {"output": f"Obsidian commands matching “{arg}”:\n{_format_hits(hits)}", "proposal": None}

    if prefix == "command:list":
        cmds = all_commands()
        if not cmds:
            return {"output": "No Obsidian command catalog has synced yet. Open the Loremaster "
                              "plugin (it pushes the catalog on load) or run “Loremaster: Refresh "
                              "commands”.", "proposal": None}
        if arg:
            sub = [c for c in cmds if arg.lower() in (c.get("source", "").lower()
                                                      + " " + c["id"].lower())]
            body = _format_hits(sub[:40]) if sub else f"No commands from “{arg}”."
            return {"output": f"Obsidian commands ({arg}):\n{body}", "proposal": None}
        pl = plugin_sources()
        descs = plugin_descriptions()
        if pl:
            plug_lines = "\n".join(
                f"- **{name}**" + (f" — {descs[name]}" if descs.get(name) else "") for name in pl)
            head = (f"{len(cmds)} Obsidian commands available across {len(pl)} plugin(s):\n"
                    f"{plug_lines}\n\nShowing the first 40 commands — narrow with "
                    f"`command:list <plugin>` or `command:search`:\n")
        else:
            head = (f"{len(cmds)} Obsidian commands available (core app only).\n"
                    f"Showing the first 40 — narrow with `command:search`:\n")
        return {"output": head + _format_hits(cmds[:40]), "proposal": None}

    if prefix == "command:run":
        if not arg:
            return {"output": "Usage: `command:run <command id or name>`.", "proposal": None}
        prop = make_proposal(arg)
        if not prop:
            hits = search(arg, limit=5)
            hint = ("\nClosest matches:\n" + _format_hits(hits)) if hits else ""
            return {"output": f"No Obsidian command matches “{arg}”.{hint}", "proposal": None}
        return {"output": f"Proposed running **{prop['name']}** (`{prop['command_id']}`).",
                "proposal": prop}

    return {"output": f"Unknown command directive: {prefix}", "proposal": None}


# The set of `command:` directives the agent loop / server recognise.
COMMAND_DIRECTIVES = {"command:search", "command:list", "command:run"}
