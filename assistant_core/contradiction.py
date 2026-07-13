"""
Contradiction detection — Milestone 37 (D-synthesis).

Finds pairs of statements across the vault that talk about the **same subject** but
**disagree** — either a different number/date for the same thing (e.g. two heights for one
mountain) or a negation flip. Deterministic-first: a cheap term-overlap + quantity gate
proposes candidate pairs with no model at all; an optional single LLM call can *confirm* a
flagged pair when a router is supplied. Surfaced through `vault:contradictions` and the
daily briefing, and (like everything else) resolved through review — never auto-edited.

Precision over recall by design: a pair is only flagged when the two sentences share
several significant terms AND carry conflicting quantities (or one negates the other), so
"5 apples" vs "3 oranges" don't trip it. False positives are expected and cheap to dismiss.
"""

from __future__ import annotations

import logging
import re
from itertools import combinations
from pathlib import Path

from assistant_core.provenance import _terms

logger = logging.getLogger("assistant")

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_NEG_RE = re.compile(r"\b(?:not|no|never|isn't|aren't|wasn't|weren't|doesn't|don't|didn't|cannot|can't|without)\b",
                     re.IGNORECASE)
_SKIP_PREFIX = ("AI/Memory/Episodes", "AI/Tests", "AI/Chat", "AI/Briefings", "AI/Proposed")
_MIN_SHARED = 3          # significant terms two sentences must share to be "about the same thing"
_MAX_CLAIMS = 500        # bound the scan


def _factual_sentences(text: str):
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "|", "```", "http")) or line.startswith("[["):
            continue
        for sent in _SENT_SPLIT.split(line):
            s = sent.strip(" -*>#\t")
            if len(s) >= 20 and _NUM_RE.search(s):
                yield s


def _collect(vault, max_claims: int = _MAX_CLAIMS) -> list[dict]:
    vault = Path(vault)
    claims: list[dict] = []
    for note in vault.rglob("*.md"):
        rel = str(note.relative_to(vault)).replace("\\", "/")
        if rel.startswith(_SKIP_PREFIX) or ".obsidian" in note.parts or ".trash" in note.parts:
            continue
        try:
            text = note.read_text(encoding="utf-8")
        except Exception:
            continue
        for s in _factual_sentences(text):
            terms = set(_terms(s))
            nums = set(_NUM_RE.findall(s))
            if len(terms) >= _MIN_SHARED and nums:
                claims.append({"note": rel, "text": s, "terms": terms, "nums": nums,
                               "neg": bool(_NEG_RE.search(s))})
                if len(claims) >= max_claims:
                    return claims
    return claims


def detect(vault, limit: int = 20) -> list[dict]:
    """Candidate contradiction pairs, highest subject-overlap first. Each:
    {a:{note,text}, b:{note,text}, shared:[terms], reason:'quantity'|'negation'}."""
    claims = _collect(vault)
    # index by term so we only compare sentences that share vocabulary
    index: dict[str, list[int]] = {}
    for i, c in enumerate(claims):
        for t in c["terms"]:
            index.setdefault(t, []).append(i)

    seen: set[tuple[int, int]] = set()
    pairs: list[dict] = []
    for idxs in index.values():
        if len(idxs) < 2:
            continue
        for a, b in combinations(idxs, 2):
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            ca, cb = claims[a], claims[b]
            shared = ca["terms"] & cb["terms"]
            if len(shared) < _MIN_SHARED or ca["note"] == cb["note"] and ca["text"] == cb["text"]:
                continue
            reason = None
            if ca["nums"] and cb["nums"] and ca["nums"] != cb["nums"]:
                reason = "quantity"          # same subject, different numbers
            elif ca["neg"] != cb["neg"]:
                reason = "negation"          # one asserts, one denies
            if reason:
                pairs.append({
                    "a": {"note": ca["note"], "text": ca["text"]},
                    "b": {"note": cb["note"], "text": cb["text"]},
                    "shared": sorted(shared), "reason": reason, "score": len(shared),
                })
    pairs.sort(key=lambda p: -p["score"])
    return pairs[:limit]


def confirm_pair(router, pair: dict, private: bool = True) -> bool | None:
    """Optional single low-temp LLM check that a flagged pair is a real contradiction.
    Returns True/False, or None if no router / the call fails. Never raises.
    `private` defaults to True: this sends note-derived text to a model, so it must stay on
    no-train providers unless a caller that knows the notes are non-private opts out — the
    project's promise is that private note content never goes to a train-on-data provider."""
    if router is None:
        return None
    try:
        from assistant_core.providers.base_provider import Message
        q = ("Do these two statements contradict each other? Answer only YES or NO.\n"
             f"1) {pair['a']['text']}\n2) {pair['b']['text']}")
        reply, _ = router.generate([Message(role="user", content=q)], task="verify",
                                   private=private, allow_webui=False)
        return (reply or "").strip().upper().startswith("YES")
    except Exception as exc:
        logger.info(f"[contradiction] confirm failed: {exc}")
        return None


def render_report(pairs: list[dict]) -> str:
    if not pairs:
        return "✓ No contradictions detected."
    lines = [f"⚠ {len(pairs)} possible contradiction(s):", ""]
    for p in pairs:
        lines.append(f"- **{p['reason']}** (shared: {', '.join(p['shared'][:4])})")
        lines.append(f"    - {p['a']['note']}: {p['a']['text']}")
        lines.append(f"    - {p['b']['note']}: {p['b']['text']}")
    return "\n".join(lines)
