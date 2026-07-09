"""
Self-diagnosis: read Loremaster's own logs — v1.9.

The service logs to `logs/assistant.log` (daily-rotated, 7 days kept) in the repo root, which
is **outside the vault**, so the normal vault: read/search commands can't see it. This helper
lets the assistant (and the user) pull recent log lines to diagnose what went wrong.

`vault:logs [N | errors | today]`:
  - (no arg)  → the last 60 lines of the active log
  - `<N>`     → the last N lines
  - `errors`  → recent WARNING/ERROR/CRITICAL lines (across today's + rotated files)
  - `today`   → all of today's lines

Read-only; never raises. Private-safe (logs stay on the machine — this just surfaces them).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("assistant")

DEFAULT_TAIL = 60
MAX_LINES = 500
_LEVEL_RE = re.compile(r"\|\s*(WARNING|ERROR|CRITICAL)\s*\|")


def _log_files() -> list[Path]:
    """Active log first, then rotated backups (assistant.log.YYYY-MM-DD), newest-first."""
    from assistant_core.paths import LOGS_DIR
    active = LOGS_DIR / "assistant.log"
    files = [active] if active.exists() else []
    backups = sorted(LOGS_DIR.glob("assistant.log.*"), reverse=True)
    return files + backups


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def read_logs(mode: str = "") -> dict:
    """Return {mode, source, lines: [...], text, error}. `mode` is '', a number, 'errors', or 'today'."""
    mode = (mode or "").strip().lower()
    files = _log_files()
    if not files:
        return {"mode": mode or "tail", "source": None, "lines": [], "text": "",
                "error": "no log file yet (logs/assistant.log not found)"}

    active = files[0]

    if mode == "errors":
        hits: list[str] = []
        for f in files:                       # scan active + rotated until we have enough
            for ln in _read_lines(f):
                if _LEVEL_RE.search(ln):
                    hits.append(ln)
            if len(hits) >= MAX_LINES:
                break
        lines = hits[-MAX_LINES:]
        src = "errors (WARNING+ across recent logs)"
    elif mode == "today":
        today = datetime.now().strftime("%Y-%m-%d")
        lines = [ln for ln in _read_lines(active) if ln.startswith(today)][-MAX_LINES:]
        src = f"{active.name} (today {today})"
    else:
        try:
            n = min(int(mode), MAX_LINES) if mode else DEFAULT_TAIL
        except ValueError:
            n = DEFAULT_TAIL
        lines = _read_lines(active)[-n:]
        src = f"{active.name} (last {n})"

    return {"mode": mode or "tail", "source": src, "lines": lines,
            "text": "\n".join(lines), "error": None}


def format_reply(rep: dict) -> str:
    """Human-readable reply for the vault:logs command."""
    if rep.get("error"):
        return f"Logs: {rep['error']}."
    if not rep["lines"]:
        return f"Logs ({rep['source']}): nothing to show."
    body = "\n".join(rep["lines"])
    return f"**Logs — {rep['source']}** ({len(rep['lines'])} line(s)):\n\n```\n{body}\n```"
