"""
Structured & exact search — Milestone 26.

A small, precise query grammar to complement semantic Vault QA and literal `vault:search`:

    tag:sermon            note has #sermon or frontmatter tags: sermon
    path:06 - Projects    note path starts with this
    fm:project=camping    frontmatter field equals value
    "exact phrase"        quoted exact substring (case-insensitive)
    antichrist            a bare word that must appear
    ESV NEAR/3 antichrist two words within N words of each other

All predicates are ANDed. Pure/deterministic (no LLM, no embeddings). Derived/log trees
are skipped. Powers `vault:query <expr>`.
"""

from __future__ import annotations

import re
from pathlib import Path

from assistant_core.watcher.frontmatter_parser import FrontmatterParser

_SKIP = ("AI/Memory/Episodes", "AI/Chat", ".obsidian", ".git", ".trash", ".venv")
_TOKEN_RE = re.compile(r'[A-Za-z]+:"[^"]*"|"[^"]+"|\S+')   # allow key:"quoted value"
_WORD_RE = re.compile(r"\w+")
_TAG_RE = re.compile(r"#([A-Za-z][\w/-]*)")


def _note_tags(fm: dict, body: str) -> set[str]:
    tags = set()
    raw = fm.get("tags", "")
    for t in re.split(r"[,\[\]\s]+", str(raw)):
        if t.strip():
            tags.add(t.strip().lstrip("#").lower())
    for m in _TAG_RE.finditer(body):
        tags.add(m.group(1).lower())
    return tags


def _near(text_lower: str, a: str, b: str, n: int) -> bool:
    words = _WORD_RE.findall(text_lower)
    a, b = a.lower(), b.lower()
    positions_a = [i for i, w in enumerate(words) if w == a]
    positions_b = [i for i, w in enumerate(words) if w == b]
    return any(abs(i - j) <= n for i in positions_a for j in positions_b)


def _parse(query: str):
    """Return a list of predicate callables (content_lower, fm, tags, rel) -> bool."""
    tokens = [t.strip() for t in _TOKEN_RE.findall(query or "") if t.strip()]
    preds = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # NEAR as an infix: <prev> NEAR/n <next> — handled when we see NEAR
        if tok.upper().startswith("NEAR/") and 0 < i < len(tokens) - 1:
            try:
                n = int(tok.split("/", 1)[1])
            except ValueError:
                n = 5
            a, b = tokens[i - 1].strip('"'), tokens[i + 1].strip('"')
            preds.pop()  # the bare-word predicate we already added for `a`
            preds.append(lambda c, fm, tg, rel, a=a, b=b, n=n: _near(c, a, b, n))
            i += 2
            continue
        if tok.startswith("tag:"):
            val = tok[4:].strip('"').lower()
            preds.append(lambda c, fm, tg, rel, v=val: v in tg)
        elif tok.startswith("path:"):
            val = tok[5:].strip('"').lower().replace("\\", "/")
            preds.append(lambda c, fm, tg, rel, v=val: rel.lower().startswith(v))
        elif tok.startswith("fm:") and "=" in tok:
            key, _, val = tok[3:].partition("=")
            preds.append(lambda c, fm, tg, rel, k=key.lower(), v=val.lower():
                         str(fm.get(k, "")).strip().strip('"\'').lower() == v)
        else:
            phrase = tok.strip('"').lower()
            preds.append(lambda c, fm, tg, rel, p=phrase: p in c)
        i += 1
    return preds


def structured_search(vault, query: str, limit: int = 30) -> list[dict]:
    """Notes matching ALL predicates in `query`. Returns [{path}]."""
    preds = _parse(query)
    if not preds:
        return []
    vault = Path(vault)
    out = []
    for note in sorted(vault.rglob("*.md")):
        rel = str(note.relative_to(vault)).replace("\\", "/")
        if any(x in note.parts for x in _SKIP) or rel.startswith("AI/Memory/Episodes"):
            continue
        try:
            content = note.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = FrontmatterParser.extract(content)
        tags = _note_tags(fm, body)
        cl = content.lower()
        if all(p(cl, fm, tags, rel) for p in preds):
            out.append({"path": rel})
        if len(out) >= limit:
            break
    return out
