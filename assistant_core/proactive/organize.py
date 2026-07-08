"""
Auto-organize new notes — Milestone 34 (proactive, PROPOSE-ONLY).

Nightly, for notes changed since the last run, Loremaster suggests **tags** (biased to
reuse the vault's existing tags) and **related links** (semantic neighbours, every one
validated against the real vault so no `[[fake links]]` are ever proposed). The
suggestions are written to a review note under `AI/Proposed/` — **nothing touches a note
until the user approves.** Governor-paced so it never competes with the foreground or
burns the day's free-tier budget.
"""

import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from assistant_core.paths import DATA_DIR
from assistant_core.background import governor
from assistant_core.links import link_exists

logger = logging.getLogger("assistant")

PROPOSED_DIR = "AI/Proposed"
_STATE_FILE  = DATA_DIR / "organize_state.json"
_SKIP_PREFIXES = ("AI/System", "AI/Memory", "AI/Briefings", "AI/Chat", "AI/Proposed",
                  "AI/Derived", "AI/Graph", "AI/Library", "AI/Research", "AI/Tests",
                  ".trash", ".obsidian")
_TAG_RE     = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]+)")
_FM_TAGS_RE = re.compile(r"^tags:\s*\[?([^\]\n]+)\]?", re.MULTILINE)


def _read_watermark(path: Path = _STATE_FILE):
    try:
        return float(json.loads(path.read_text(encoding="utf-8"))["watermark"])
    except Exception:
        return None


def _write_watermark(ts: float, path: Path = _STATE_FILE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"watermark": ts}), encoding="utf-8")
    except Exception as exc:
        logger.debug(f"[Organize] watermark write failed: {exc}")


def _skip(rel: str) -> bool:
    return any(rel.startswith(s) for s in _SKIP_PREFIXES)


def existing_tags(vault, limit: int = 40) -> list[str]:
    """The vault's most-used tags (frontmatter + inline) — the vocabulary to reuse."""
    vault = Path(vault)
    c: Counter = Counter()
    for p in vault.rglob("*.md"):
        rel = str(p.relative_to(vault)).replace("\\", "/")
        if _skip(rel):
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in _TAG_RE.findall(txt):
            c[m.lower()] += 1
        fm = _FM_TAGS_RE.search(txt)
        if fm:
            for t in re.split(r"[,\s]+", fm.group(1)):
                t = t.strip().strip("'\"#").lower()
                if t:
                    c[t] += 1
    return [t for t, _ in c.most_common(limit)]


def _norm_tag(t: str) -> str:
    t = t.strip().strip("#'\"").lower().replace(" ", "-")
    return re.sub(r"[^a-z0-9/_-]", "", t)


def _suggest_tags(router, content: str, existing: list[str], private: bool = False) -> list[str]:
    if router is None or not getattr(router, "available_providers", None):
        return []
    from assistant_core.providers.base_provider import Message
    prompt = (
        "Suggest 2-5 topical tags for the note below. Strongly prefer reusing these existing "
        f"vault tags when they fit: {', '.join(existing[:40]) or '(none yet)'}. "
        "Return ONLY a comma-separated list of tags, lowercase, no '#'. Do not invent unrelated tags.\n\n"
        f"{content[:2000]}"
    )
    try:
        reply, _ = router.generate([Message(role="user", content=prompt)],
                                   task="extract", private=private, allow_webui=False)
    except Exception as exc:
        logger.info(f"[Organize] tag call failed: {exc}")
        return []
    out: list[str] = []
    for t in re.split(r"[,\n]", reply or ""):
        nt = _norm_tag(t)
        if nt and nt not in out:
            out.append(nt)
    return out[:5]


def _related_links(rag, note_path: str, vault) -> list[str]:
    """Semantic neighbours, each validated against the vault (no fabricated links)."""
    if rag is None or not getattr(rag, "has_index", lambda: False)():
        return []
    try:
        rel = rag.relevant_notes(note_path, k=5)
    except Exception:
        return []
    out: list[str] = []
    for r in rel:
        path = r.get("path") if isinstance(r, dict) else r
        if not path:
            continue
        stem = Path(path).stem
        if stem not in out and link_exists(stem, vault):
            out.append(stem)
    return out[:5]


def _note_is_private(text: str) -> bool:
    return bool(re.search(r"^private:\s*true", text, re.MULTILINE | re.IGNORECASE))


def suggest_for_note(note_path: str, content: str, vault, rag, router,
                     existing: list[str]) -> dict:
    private = _note_is_private(content)
    return {
        "note":    note_path,
        "tags":    _suggest_tags(router, content, existing, private=private),
        "related": _related_links(rag, note_path, vault),
    }


def run_organize(vault, config: dict | None = None, rag=None, router=None,
                 now: datetime | None = None, max_notes: int = 20) -> dict:
    config = config or {}
    now = now or datetime.now()
    vault = Path(vault)
    watermark = _read_watermark()
    existing = existing_tags(vault)

    candidates = []
    for p in vault.rglob("*.md"):
        rel = str(p.relative_to(vault)).replace("\\", "/")
        if _skip(rel):
            continue
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if watermark and mt <= watermark:
            continue
        candidates.append((mt, rel, p))
    candidates.sort(reverse=True)      # newest first

    suggestions, scanned = [], 0
    for mt, rel, p in candidates:
        if scanned >= max_notes:
            break
        if not governor.may_run(config):
            logger.info("[Organize] deferring remaining notes — governor (foreground/budget)")
            break
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        s = suggest_for_note(rel, content, vault, rag, router, existing)
        governor.record_background_call()
        scanned += 1
        if s["tags"] or s["related"]:
            suggestions.append(s)

    proposal = _write_proposal(vault, suggestions, now) if suggestions else None
    _write_watermark(now.timestamp())
    return {"notes": len(suggestions), "scanned": scanned, "proposal": proposal}


def _write_proposal(vault, suggestions: list[dict], now: datetime) -> str:
    date = now.strftime("%Y-%m-%d")
    rel = f"{PROPOSED_DIR}/organize-{date}.md"
    dest = Path(vault) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Auto-organize proposals — {date}", "",
        "> Loremaster suggests tags and related links for recently-changed notes. "
        "**Nothing is applied until you approve.** Edit or delete this note freely.", "",
    ]
    for s in suggestions:
        lines.append(f"## {s['note']}")
        if s["tags"]:
            lines.append("- **Tags:** " + " ".join(f"#{t}" for t in s["tags"]))
        if s["related"]:
            lines.append("- **Related:** " + " ".join(f"[[{r}]]" for r in s["related"]))
        lines.append("")
    dest.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"[Organize] wrote {rel} ({len(suggestions)} note(s))")
    return rel
