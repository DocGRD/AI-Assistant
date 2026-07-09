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
from assistant_core import feedback

logger = logging.getLogger("assistant")

PROPOSED_DIR = "AI/Proposed"
_STATE_FILE  = DATA_DIR / "organize_state.json"
_PENDING_FILE = DATA_DIR / "organize_pending.json"   # structured proposals for the plugin
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
    return re.sub(r"[^a-z0-9/_-]", "", t).strip("-")


_TAG_DENY = {"no-matching-tags", "none", "na", "n-a", "tags", "tag", "no-tags",
             "untagged", "no-tag", "matching", "empty"}


def _valid_tag(t: str) -> bool:
    # A real tag is short with few hyphens; this rejects prose the model turned into a
    # hyphenated blob ("consider-adding-a-new-tag-...") when it ignored "list only",
    # plus obvious "no tags" refusals — so we get clean tags or nothing, never junk.
    return (2 <= len(t) <= 25 and t.count("-") <= 2 and not t[0].isdigit()
            and t not in _TAG_DENY)


def _suggest_tags(router, content: str, existing: list[str], private: bool = False) -> list[str]:
    if router is None or not getattr(router, "available_providers", None):
        return []
    from assistant_core.providers.base_provider import Message
    prompt = (
        "Output 2-5 topical tags for the note below as a COMMA-SEPARATED LIST and nothing else — "
        "no sentences, no explanation. Each tag is 1-2 words, lowercase. Strongly prefer reusing "
        f"these existing vault tags when they fit: {', '.join(existing[:40]) or '(none yet)'}. "
        "If nothing fits, output an empty line.\n\n"
        f"{content[:2000]}"
    )
    try:
        reply, _ = router.generate([Message(role="user", content=prompt)],
                                   task="extract", private=private, allow_webui=False)
    except Exception as exc:
        logger.info(f"[Organize] tag call failed: {exc}")
        return []
    # If the model ignored the format and wrote a sentence, the comma-split yields long
    # hyphenated blobs — _valid_tag drops them, so we get clean tags or nothing (never junk).
    out: list[str] = []
    for t in re.split(r"[,\n]", reply or ""):
        nt = _norm_tag(t)
        if nt and _valid_tag(nt) and nt not in out and not feedback.suppressed("tag", nt):
            out.append(nt)                        # drop tags the user keeps rejecting
    out.sort(key=lambda t: 0 if feedback.boosted("tag", t) else 1)   # prefer accepted tags
    return out[:5]


def _related_links(rag, note_path: str, vault, graph=None) -> list[str]:
    """Semantic + graph neighbours via the shared linking service — every link validated
    against the vault (no fabricated links) and feedback-filtered for this note."""
    from assistant_core import linking
    return linking.related(vault, note_path, k=5, rag=rag, graph=graph)


def _note_is_private(text: str) -> bool:
    return bool(re.search(r"^private:\s*true", text, re.MULTILINE | re.IGNORECASE))


def _related_paths(rag, note_path: str, k: int = 6) -> list[str]:
    """Rel paths of the note's semantic neighbours — for folder/project inference (M38)."""
    if rag is None or not getattr(rag, "has_index", lambda: False)():
        return []
    try:
        return [r.get("path") for r in rag.relevant_notes(note_path, k=k) if r.get("path")]
    except Exception:
        return []


def _suggest_folder(vault, note_rel: str, related_paths: list[str]) -> str:
    """A better home folder for a mis-filed note: where a clear majority of its neighbours
    live, if that differs from its current folder (and isn't a system dir). '' = leave it."""
    cur = str(Path(note_rel).parent).replace("\\", "/")
    cur = "" if cur == "." else cur
    c: Counter = Counter()
    for rp in related_paths:
        d = str(Path(rp).parent).replace("\\", "/")
        if d and d != "." and not _skip(rp):
            c[d] += 1
    if not c:
        return ""
    folder, n = c.most_common(1)[0]
    return folder if n >= 2 and folder != cur else ""


def _suggest_project(vault, content: str, related_paths: list[str]) -> str:
    """A project for a note that lacks one, from the dominant `project:` among its neighbours."""
    if re.search(r"^project:\s*\S", content, re.MULTILINE | re.IGNORECASE):
        return ""                                     # already assigned
    from assistant_core.watcher.frontmatter_parser import FrontmatterParser
    c: Counter = Counter()
    for rp in related_paths:
        try:
            fm, _ = FrontmatterParser.extract((Path(vault) / rp).read_text(encoding="utf-8"))
        except Exception:
            continue
        pr = str(fm.get("project", "")).strip().strip("'\"")
        if pr:
            c[pr] += 1
    if not c:
        return ""
    proj, n = c.most_common(1)[0]
    return proj if n >= 2 else ""


def suggest_for_note(note_path: str, content: str, vault, rag, router,
                     existing: list[str]) -> dict:
    private = _note_is_private(content)
    rel_paths = _related_paths(rag, note_path)
    return {
        "note":    note_path,
        "tags":    _suggest_tags(router, content, existing, private=private),
        "related": _related_links(rag, note_path, vault),
        "folder":  _suggest_folder(vault, note_path, rel_paths),   # M38 auto-filing
        "project": _suggest_project(vault, content, rel_paths),    # M38 project association
    }


def run_organize(vault, config: dict | None = None, rag=None, router=None,
                 now: datetime | None = None, max_notes: int = 20, force: bool = False) -> dict:
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
        if not force and not governor.may_run(config):   # force = user ran it on demand
            logger.info("[Organize] deferring remaining notes — governor (foreground/budget)")
            break
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        s = suggest_for_note(rel, content, vault, rag, router, existing)
        governor.record_background_call()
        scanned += 1
        if s["tags"] or s["related"] or s.get("folder") or s.get("project"):
            suggestions.append(s)

    proposal = _write_proposal(vault, suggestions, now) if suggestions else None
    if suggestions:
        _merge_pending(suggestions)          # structured record for one-click approve
    _write_watermark(now.timestamp())
    return {"notes": len(suggestions), "scanned": scanned, "proposal": proposal}


# ---------------------------------------------------------------------------
# Pending store + apply (used by the plugin Proactive panel)
# ---------------------------------------------------------------------------

def load_pending() -> list[dict]:
    try:
        return json.loads(_PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_pending(items: list[dict]) -> None:
    try:
        _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PENDING_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug(f"[Organize] pending write failed: {exc}")


def _merge_pending(suggestions: list[dict]) -> None:
    by_note = {s["note"]: s for s in load_pending()}
    for s in suggestions:
        by_note[s["note"]] = {"note": s["note"], "tags": s["tags"], "related": s["related"],
                              "folder": s.get("folder", ""), "project": s.get("project", "")}
    _save_pending(list(by_note.values()))


def remove_pending(note: str) -> list[dict]:
    items = [s for s in load_pending() if s.get("note") != note]
    _save_pending(items)
    return items


def _merge_tags(text: str, tags: list[str]) -> str:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if m:
        fm = m.group(1)
        tm = re.search(r"^tags:\s*\[?([^\]\n]*)\]?\s*$", fm, re.MULTILINE)
        if tm:
            existing = {t.strip().strip("'\"#") for t in re.split(r"[,\s]+", tm.group(1)) if t.strip()}
            merged = ", ".join(sorted(existing | set(tags)))
            new_fm = re.sub(r"^tags:.*$", f"tags: [{merged}]", fm, count=1, flags=re.MULTILINE)
        else:
            new_fm = fm + f"\ntags: [{', '.join(tags)}]"
        return text[:m.start()] + f"---\n{new_fm}\n---\n" + text[m.end():]
    return f"---\ntags: [{', '.join(tags)}]\n---\n\n" + text


def apply_suggestion(vault, note: str, tags: list[str] | None = None,
                     related: list[str] | None = None) -> bool:
    """Commit a whole proposal: merge tags + append a validated Related section, and record
    every applied tag/link as an accept so future suggestions learn from it."""
    p = Path(vault) / note
    if not p.exists():
        remove_pending(note)
        return False
    text = p.read_text(encoding="utf-8")
    if tags:
        text = _merge_tags(text, tags)
        for t in tags:
            feedback.record("tag", t, True)
    if related and "## Related" not in text:
        # re-validate links at apply time (the vault may have changed since proposal)
        valid = [r for r in related if link_exists(r, vault)]
        if valid:
            text = text.rstrip() + "\n\n## Related\n\n" + "\n".join(f"- [[{r}]]" for r in valid) + "\n"
            for r in valid:
                feedback.record("link", r, True, scope=note)
    p.write_text(text, encoding="utf-8")
    remove_pending(note)
    logger.info(f"[Organize] applied suggestion to {note}")
    return True


# ---------------------------------------------------------------------------
# Per-item apply / reject (M35.1) — resolve a single tag or link, and learn from it
# ---------------------------------------------------------------------------

def _update_pending_item(note: str, kind: str, value: str) -> bool:
    """Remove one resolved item (tag/link/folder/project) from a note's pending entry; drop
    the note once nothing is left to review."""
    list_key = {"tag": "tags", "link": "related"}.get(kind)
    scalar_key = {"folder": "folder", "project": "project"}.get(kind)
    out, changed = [], False
    for s in load_pending():
        if s.get("note") != note:
            out.append(s)
            continue
        if list_key:
            vals = [v for v in s.get(list_key, []) if v != value]
            if len(vals) != len(s.get(list_key, [])):
                changed = True
            s[list_key] = vals
        elif scalar_key and s.get(scalar_key):
            s[scalar_key] = ""
            changed = True
        if s.get("tags") or s.get("related") or s.get("folder") or s.get("project"):
            out.append(s)          # keep the note while it still has pending items
    _save_pending(out)
    return changed


def _apply_tag(vault, note: str, tag: str) -> bool:
    p = Path(vault) / note
    if not p.exists():
        remove_pending(note)
        return False
    p.write_text(_merge_tags(p.read_text(encoding="utf-8"), [tag]), encoding="utf-8")
    return True


def _apply_link(vault, note: str, link: str) -> bool:
    p = Path(vault) / note
    if not p.exists():
        remove_pending(note)
        return False
    if not link_exists(link, vault):          # re-validate at apply time
        return False
    text = p.read_text(encoding="utf-8")
    if f"[[{link}]]" in text:
        return True                           # already linked — nothing to do
    if "## Related" in text:
        text = text.rstrip() + f"\n- [[{link}]]\n"   # add under the existing section
    else:
        text = text.rstrip() + f"\n\n## Related\n\n- [[{link}]]\n"
    p.write_text(text, encoding="utf-8")
    return True


def _merge_fm_field(text: str, field: str, value: str) -> str:
    """Set a scalar frontmatter field (create the block if there's none)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if m:
        fm = m.group(1)
        if re.search(rf"^{field}:", fm, re.MULTILINE):
            new_fm = re.sub(rf"^{field}:.*$", f"{field}: {value}", fm, count=1, flags=re.MULTILINE)
        else:
            new_fm = fm + f"\n{field}: {value}"
        return text[:m.start()] + f"---\n{new_fm}\n---\n" + text[m.end():]
    return f"---\n{field}: {value}\n---\n\n" + text


def _apply_folder(vault, note: str, folder: str) -> bool:
    """Move the note into `folder` (safe — Obsidian wikilinks resolve by name, not path)."""
    import shutil
    src = Path(vault) / note
    if not src.exists():
        remove_pending(note)
        return False
    if _skip(f"{folder}/x"):                       # never file into system dirs
        return False
    try:
        dst_dir = Path(vault) / folder
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        if dst.exists() or dst.resolve() == src.resolve():
            return False
        shutil.move(str(src), str(dst))
        return True
    except Exception as exc:
        logger.info(f"[Organize] folder move failed: {exc}")
        return False


def _apply_project(vault, note: str, project: str) -> bool:
    p = Path(vault) / note
    if not p.exists():
        remove_pending(note)
        return False
    p.write_text(_merge_fm_field(p.read_text(encoding="utf-8"), "project", project), encoding="utf-8")
    return True


def apply_one(vault, note: str, kind: str, value: str) -> bool:
    """Apply a single suggested item (tag/link/folder/project), record positive feedback, and
    remove just that item from pending (dropping the note when nothing's left)."""
    if kind == "tag":
        ok = _apply_tag(vault, note, value)
    elif kind == "link":
        ok = _apply_link(vault, note, value)
    elif kind == "folder":
        ok = _apply_folder(vault, note, value)
    elif kind == "project":
        ok = _apply_project(vault, note, value)
    else:
        return False
    if ok:
        feedback.record(kind, value, True, scope=(note if kind != "tag" else ""))
        if kind == "folder":
            remove_pending(note)          # the file moved → its whole pending entry is stale
        else:
            _update_pending_item(note, kind, value)
        logger.info(f"[Organize] applied {kind} '{value}' to {note}")
    return ok


def reject_one(note: str, kind: str, value: str) -> bool:
    """Dismiss a single suggested item — record a reject (learning) and drop it from pending."""
    if kind not in ("tag", "link", "folder", "project"):
        return False
    feedback.record(kind, value, False, scope=(note if kind != "tag" else ""))
    return _update_pending_item(note, kind, value)


def reject_all(note: str) -> None:
    """Dismiss a whole note's proposal, recording each tag/link as a reject (learning)."""
    sugg = next((s for s in load_pending() if s.get("note") == note), None)
    if sugg:
        for t in sugg.get("tags", []):
            feedback.record("tag", t, False)
        for r in sugg.get("related", []):
            feedback.record("link", r, False, scope=note)
    remove_pending(note)


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
