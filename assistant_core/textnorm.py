"""
Exotic-Unicode normalization for text that comes back from models.

Some providers (and reasoning models especially) emit **narrow no-break spaces** (U+202F),
**no-break spaces** (U+00A0), **non-breaking hyphens** (U+2011), and zero-width characters —
often around numbers and names ("1␣John␣4", "1:1‑4"). These are visually identical to their
plain ASCII forms but are DIFFERENT code points, which has caused real bugs: a note name with
U+202F doesn't match its real filename (broken `[[wikilink]]`, missed self-link), and the same
string with vs. without the exotic char de-dupes as two different facts.

Episodes log model output verbatim and are the **source data for memory consolidation**, so we
normalize on write (future episodes stay clean) and when consolidation reads them (old episodes
still yield clean facts).

We deliberately preserve **en/em dashes** (–, —) and regular whitespace/newlines — those are
intentional punctuation, not model noise.
"""

from __future__ import annotations

# exotic spaces → a regular space
_SPACES = (0x00A0, 0x2005, 0x2007, 0x2009, 0x202F)
# hyphen look-alikes with special behaviour → a regular hyphen (NOT en/em dash, which are real)
_HYPHENS = (0x2010, 0x2011)
# zero-width / invisible → removed
_ZERO_WIDTH = (0x200B, 0x2060, 0xFEFF, 0x00AD)

_TRANS: dict[int, str | None] = {}
for _c in _SPACES:
    _TRANS[_c] = " "
for _c in _HYPHENS:
    _TRANS[_c] = "-"
for _c in _ZERO_WIDTH:
    _TRANS[_c] = None          # str.translate deletes on None


def normalize_exotic(text: str) -> str:
    """Replace exotic Unicode whitespace/hyphens models emit with plain ASCII equivalents,
    and strip zero-width characters. Newlines, ordinary spacing, and en/em dashes are kept."""
    if not text:
        return text
    return text.translate(_TRANS)


def has_exotic(text: str) -> bool:
    """True if `text` contains any character normalize_exotic would change (for auditing)."""
    return any(ord(ch) in _TRANS for ch in (text or ""))
