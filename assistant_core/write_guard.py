"""
Trust on write — Milestone 37.

The hallucination guard (M30, `verify.guard_answer`) protects *answers*. This extends the
same edge to *writes*: when the agent creates or edits a note, check the **factual claims**
it asserts against the rest of the vault and flag the ones nothing supports — so "nothing
untrue enters the vault" covers stored content, not just chat.

Deterministic and private-safe: it reuses the term-overlap provenance audit (M25,
`provenance.find_sources`) — no model, no web — so it runs on every write without cost and
never leaks private notes. Conservative by design: only sentences that actually *assert a
fact* (a number, year, percentage, or unit) are checked, so ordinary prose and the user's
own thoughts don't get flagged.

Config `write_guard`:
  - ``off``    — do nothing
  - ``flag``   — append a callout listing unsourced factual claims (default)
  - ``source`` — as ``flag``, plus a **Sources** list citing the notes that DO support claims
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from assistant_core.provenance import find_sources

logger = logging.getLogger("assistant")

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
# A sentence "asserts a fact" if it carries a checkable quantity: a 2+ digit number, a
# 4-digit year, a percentage, or a common unit. Bare single digits are ignored (too noisy).
_FACTUAL = re.compile(
    r"\b\d{2,}\b|\b\d{4}\b|\d+\s?%|\b\d+(?:\.\d+)?\s?"
    r"(?:km|kg|lb|lbs|mi|miles|ft|feet|m|cm|mm|kmh|mph|°|percent|million|billion|trillion|bce|bc|ad|ce)\b",
    re.IGNORECASE,
)
_MAX_CLAIMS = 8   # bound the vault scans per write


def _claims(text: str) -> list[str]:
    """Factual-assertion sentences worth checking (skips headings, quotes, links, code)."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if (not line or line.startswith(("#", ">", "|", "```", "http"))
                or line.startswith("[[") or line.startswith("![")):
            continue
        for sent in _SENT_SPLIT.split(line):
            s = sent.strip(" -*>#\t")
            if len(s) >= 20 and _FACTUAL.search(s) and s not in out:
                out.append(s)
                if len(out) >= _MAX_CLAIMS:
                    return out
    return out


def guard_content(vault, content: str, config: dict | None = None,
                  private: bool = False) -> tuple[str, str]:
    """Annotate `content` per the `write_guard` policy. Returns (content, status):
    off | clean | flagged. Never raises — a guard failure must not block the write."""
    policy = (config or {}).get("write_guard", "flag")
    if policy == "off" or not (content or "").strip() or not vault:
        return content, "off"
    try:
        claims = _claims(content)
        if not claims:
            return content, "clean"
        unsourced, sourced = [], []
        for c in claims:
            rep = find_sources(vault, c, limit=2)
            (sourced if rep.get("sourced") else unsourced).append((c, rep))

        body = content.rstrip()
        if policy == "source" and sourced:
            lines = []
            for c, rep in sourced:
                stems = [Path(s["path"]).stem for s in rep.get("sources", [])[:2]]
                if stems:
                    lines.append(f"- \"{c[:70]}\" — " + ", ".join(f"[[{s}]]" for s in stems))
            if lines:
                body += "\n\n**Sources:**\n" + "\n".join(lines)

        if unsourced:
            body += ("\n\n> [!warning] Unsourced claims — verify before relying on these\n"
                     + "\n".join(f"> - {c[:120]}" for c, _ in unsourced))
            logger.info(f"[write_guard] flagged {len(unsourced)} unsourced claim(s)")
            return body, "flagged"
        return body, "clean"
    except Exception as exc:                       # never block a write on a guard error
        logger.debug(f"[write_guard] skipped: {exc}")
        return content, "off"
