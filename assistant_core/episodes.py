"""Episode line formatters.

Each returns one Markdown line for the daily episode log under
`AI/Memory/Episodes/`. Kept separate from the orchestration in `app.py` because
the HTTP server and the watcher also use them (injected as `ep_*_fn` callables).
"""

from datetime import datetime as _dt


def _ts() -> str:
    return _dt.now().strftime("%H:%M")


def ep_vault(tool: str, detail: str) -> str:
    return f"- **{_ts()}** `{tool}` — {detail}\n"


def ep_remember(fact: str) -> str:
    return f"- **{_ts()}** Remembered: {fact}\n"


def ep_chat(user: str, assistant: str, provider: str = "") -> str:
    reply_lines = assistant.strip().splitlines()
    indented    = "\n> ".join(reply_lines)
    tag         = f" [{provider}]" if provider else ""
    return f"\n**{_ts()}{tag} — You:** {user}\n> {indented}\n"


def ep_error(detail: str) -> str:
    return f"- **{_ts()}** ⚠ {detail}\n"


def ep_handoff(direction: str, detail: str) -> str:
    return f"- **{_ts()}** 🌐 Web handoff {direction} — {detail}\n"
