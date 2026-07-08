"""
Vault analytics — Milestone 38 (D-synthesis, "explain my vault").

A read-only pass that helps the vault understand itself: which notes are **orphans**
(nothing links to or from them), which are **stale**, which assert **unsourced** facts,
what the **tag** and **topic** distribution looks like, the **most-linked** hubs, and
near-duplicate **tags worth merging**. Everything here is deterministic and read-only —
`vault:analytics` writes a report note; nothing else is touched.

The same helpers feed the vault-state daily briefing (C5), so "state of your vault" is
computed in one place.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

from assistant_core.links import link_targets, resolve_link

logger = logging.getLogger("assistant")

REPORTS_DIR = "AI/Reports"
_SKIP_PREFIX = ("AI/", ".obsidian", ".trash", ".git", ".venv")


def _notes(vault: Path):
    for p in vault.rglob("*.md"):
        rel = str(p.relative_to(vault)).replace("\\", "/")
        if rel.startswith(_SKIP_PREFIX):
            continue
        yield rel, p


def link_index(vault) -> dict[str, dict[str, set]]:
    """{note_rel: {'out': {stems}, 'in': {stems}}} from resolved wikilinks."""
    vault = Path(vault)
    idx: dict[str, dict[str, set]] = {}
    for rel, p in _notes(vault):
        idx.setdefault(rel, {"out": set(), "in": set()})
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for tgt in link_targets(text):
            dest = resolve_link(tgt, vault)
            if not dest:
                continue
            drel = str(dest.relative_to(vault)).replace("\\", "/")
            if drel == rel:
                continue
            idx[rel]["out"].add(drel)
            idx.setdefault(drel, {"out": set(), "in": set()})["in"].add(rel)
    return idx


def orphans(vault, idx: dict | None = None) -> list[str]:
    """Notes with no inbound and no outbound links."""
    idx = idx if idx is not None else link_index(vault)
    return sorted(r for r, v in idx.items() if not v["out"] and not v["in"])


def most_linked(vault, n: int = 10, idx: dict | None = None) -> list[tuple[str, int]]:
    idx = idx if idx is not None else link_index(vault)
    ranked = sorted(((r, len(v["in"])) for r, v in idx.items()), key=lambda kv: -kv[1])
    return [(r, c) for r, c in ranked if c > 0][:n]


def stale_notes(vault, days: int = 180, now: datetime | None = None) -> list[str]:
    """Notes not modified in `days` days (oldest first)."""
    vault = Path(vault)
    now = now or datetime.now()
    cutoff = now.timestamp() - days * 86400
    out = []
    for rel, p in _notes(vault):
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if mt < cutoff:
            out.append((mt, rel))
    out.sort()
    return [r for _, r in out]


def tag_distribution(vault) -> Counter:
    from assistant_core.proactive.organize import _TAG_RE, _FM_TAGS_RE
    import re
    vault = Path(vault)
    c: Counter = Counter()
    for _, p in _notes(vault):
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
    return c


def unsourced_notes(vault, limit: int = 15, max_scan: int = 400) -> list[str]:
    """Notes asserting factual quantities that nothing else in the vault supports.

    Loads every note's text **once** and checks claims against that in-memory corpus, so it
    stays fast on large vaults (the naive version re-read the whole vault per note → minutes).
    """
    from math import ceil
    from assistant_core.write_guard import _claims
    from assistant_core.provenance import _terms
    vault = Path(vault)

    corpus: list[tuple[str, str]] = []            # (rel, lowercased text), single disk pass
    for rel, p in _notes(vault):
        try:
            corpus.append((rel, p.read_text(encoding="utf-8").lower()))
        except Exception:
            continue

    out: list[str] = []
    for rel, low in corpus[:max_scan]:
        claims = _claims(low)
        if not claims:
            continue
        supported = False
        for c in claims[:3]:
            terms = _terms(c)
            if not terms:
                continue
            need = max(2, ceil(len(terms) / 2))
            if any(orel != rel and sum(1 for t in terms if t in olow) >= need
                   for orel, olow in corpus):
                supported = True
                break
        if not supported:
            out.append(rel)
            if len(out) >= limit:
                break
    return out


def suggest_tag_merges(vault, embedder=None, threshold: float = 0.86) -> list[tuple[str, str, float]]:
    """Near-duplicate tag pairs worth merging (e.g. #prayer / #prayers), by embedding
    similarity. Returns (keep, merge_into_keep, score) with the more-used tag as `keep`.
    Needs an embedder; returns [] without one."""
    if embedder is None:
        return []
    dist = tag_distribution(vault)
    tags = [t for t, _ in dist.most_common(60)]
    if len(tags) < 2:
        return []
    try:
        import numpy as np
        vecs = embedder.embed([t.replace("-", " ").replace("/", " ") for t in tags])
    except Exception as exc:
        logger.info(f"[analytics] tag embedding failed: {exc}")
        return []
    out: list[tuple[str, str, float]] = []
    seen: set[frozenset] = set()
    for i in range(len(tags)):
        for j in range(i + 1, len(tags)):
            key = frozenset((tags[i], tags[j]))
            if key in seen:
                continue
            score = float(np.dot(vecs[i], vecs[j]))
            if score >= threshold:
                seen.add(key)
                a, b = tags[i], tags[j]
                keep, merge = (a, b) if dist[a] >= dist[b] else (b, a)
                out.append((keep, merge, round(score, 3)))
    out.sort(key=lambda t: -t[2])
    return out[:15]


def build_report(vault, embedder=None, now: datetime | None = None) -> dict:
    vault = Path(vault)
    idx = link_index(vault)
    total = len(idx)
    dist = tag_distribution(vault)
    return {
        "total_notes": total,
        "orphans": orphans(vault, idx),
        "most_linked": most_linked(vault, 10, idx),
        "stale": stale_notes(vault, now=now),
        "unsourced": unsourced_notes(vault),
        "top_tags": dist.most_common(15),
        "tag_merges": suggest_tag_merges(vault, embedder),
    }


def render_report(rep: dict, date: str) -> str:
    L = [f"# Vault analytics — {date}", "",
         f"**{rep['total_notes']}** notes analyzed.  *Read-only report; nothing was changed.*", ""]
    L += ["## Most-linked (hubs)", ""]
    L += [f"- [[{Path(r).stem}]] — {c} inbound" for r, c in rep["most_linked"]] or ["- (none)"]
    L += ["", f"## Orphans — no links in or out ({len(rep['orphans'])})", ""]
    L += [f"- [[{Path(r).stem}]]" for r in rep["orphans"][:20]] or ["- (none 🎉)"]
    if len(rep["orphans"]) > 20:
        L.append(f"- …and {len(rep['orphans']) - 20} more")
    L += ["", f"## Stale — untouched 180+ days ({len(rep['stale'])})", ""]
    L += [f"- [[{Path(r).stem}]]" for r in rep["stale"][:15]] or ["- (none)"]
    L += ["", f"## Unsourced factual notes ({len(rep['unsourced'])})", ""]
    L += [f"- [[{Path(r).stem}]]" for r in rep["unsourced"]] or ["- (none)"]
    L += ["", "## Top tags", ""]
    L += [f"- #{t} × {n}" for t, n in rep["top_tags"]] or ["- (none)"]
    if rep["tag_merges"]:
        L += ["", "## Suggested tag merges (near-duplicates)", ""]
        L += [f"- `#{m}` → `#{k}`  ({s})" for k, m, s in rep["tag_merges"]]
    L += ["", "---", "*Generated by Loremaster — `vault:analytics`.*"]
    return "\n".join(L)


def write_report(vault, embedder=None, now: datetime | None = None) -> str:
    now = now or datetime.now()
    date = now.strftime("%Y-%m-%d")
    rep = build_report(vault, embedder, now)
    rel = f"{REPORTS_DIR}/vault-analytics-{date}.md"
    dest = Path(vault) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_report(rep, date), encoding="utf-8")
    logger.info(f"[analytics] wrote {rel}")
    return rel
