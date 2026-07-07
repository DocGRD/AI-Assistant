"""
Wikilink resolution + dangling-link neutralisation — Milestone 30 (anti-hallucination).

Single source of truth for `[[wikilink]]` handling. Models routinely invent links to
notes that do not exist ("notes full of fake links"); before any AI-authored content is
written to the vault, `neutralize_dangling` resolves every `[[link]]` against the real
vault and, by policy, strips the ones that point nowhere so the note has no dead links.

Deterministic and local — no LLM, no network.
"""

import re
from pathlib import Path

# [[Target]] · [[Target|Alias]] · [[Target#Heading]] · [[Target#Heading|Alias]]
# The negative lookbehind skips embeds (![[...]]) so image/note embeds are left intact.
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]|#\n]+)(#[^\]|\n]*)?(?:\|([^\]\n]*))?\]\]")


def link_targets(text: str) -> list[str]:
    """Every wikilink target in `text`, in order (deduped preserving order)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in WIKILINK_RE.finditer(text or ""):
        t = m.group(1).strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def resolve_link(target: str, vault) -> Path | None:
    """
    Resolve a link to a single unambiguous note Path: a direct relative path (with an
    implied `.md`), else exactly one note whose stem matches. 0 or >1 matches → None.
    (Mirrors the historic `GetLinkedNotesTool._resolve` — used when a note must be *read*.)
    """
    vault = Path(vault)
    name = (target or "").strip()
    if not name:
        return None
    candidate = vault / name
    if not candidate.suffix:
        candidate = candidate.with_suffix(".md")
    if candidate.exists():
        return candidate
    stem = Path(name).stem.lower()
    matches = [p for p in vault.rglob("*.md") if p.stem.lower() == stem]
    return matches[0] if len(matches) == 1 else None


def _exists(name: str, vault: Path, stems: set[str]) -> bool:
    """True if the link points at *at least one* real note (existence, not uniqueness)."""
    name = (name or "").strip()
    if not name:
        return True                      # [[#Heading]] same-note link — leave alone
    candidate = vault / name
    if not candidate.suffix:
        candidate = candidate.with_suffix(".md")
    if candidate.exists():
        return True
    return Path(name).stem.lower() in stems


def link_exists(target: str, vault) -> bool:
    """Convenience single-shot existence check (builds the stem set each call)."""
    vault = Path(vault)
    if not vault.exists():
        return True
    stems = {p.stem.lower() for p in vault.rglob("*.md")}
    return _exists(target, vault, stems)


def neutralize_dangling(text: str, vault, policy: str = "strip") -> tuple[str, list[str]]:
    """
    Resolve every `[[link]]` in `text` against `vault`; handle the dead ones per `policy`:
      - "strip" (default): replace `[[Ghost|alias]]` with plain text (`alias` or the target's
        last path component) — no dead link remains.
      - "flag": keep the link but append a ⚠ marker.
      - "off": no change.
    Valid links are left byte-for-byte untouched. Returns (new_text, removed_targets).
    """
    if not text or policy == "off":
        return text, []
    vault = Path(vault)
    if not vault.exists():
        return text, []
    stems = {p.stem.lower() for p in vault.rglob("*.md")}
    removed: list[str] = []

    def _sub(m: "re.Match") -> str:
        target = m.group(1).strip()
        alias  = (m.group(3) or "").strip()
        if _exists(target, vault, stems):
            return m.group(0)                      # keep valid links verbatim
        removed.append(target)
        if policy == "flag":
            return f"{m.group(0)} ⚠"
        return alias or target.split("/")[-1]      # strip → plain display text

    clean = WIKILINK_RE.sub(_sub, text)
    seen: set[str] = set()
    uniq = [t for t in removed if not (t in seen or seen.add(t))]
    return clean, uniq
