"""
Scripture reference parsing — Milestone 24, Slice 1.

Detect and normalise Bible references ("1 Jn 2:18", "1 John 2:18-20", "John 3:16") anywhere
in text. A reference becomes a canonical entity string like "1 John 2:18-20" so notes that
touch the same passage can be linked and gathered (Passage Guide). Pure + heavily testable.
"""

from __future__ import annotations

import re

# canonical book name → aliases (lower-cased, no spaces/dots for matching)
_BOOKS: dict[str, list[str]] = {
    "Genesis": ["gen", "ge"], "Exodus": ["exod", "exo", "ex"], "Leviticus": ["lev", "lv"],
    "Numbers": ["num", "nm"], "Deuteronomy": ["deut", "dt"], "Joshua": ["josh", "jos"],
    "Judges": ["judg", "jdg"], "Ruth": ["ru"], "1 Samuel": ["1sam", "1sm", "1sa"],
    "2 Samuel": ["2sam", "2sm", "2sa"], "1 Kings": ["1kgs", "1ki"], "2 Kings": ["2kgs", "2ki"],
    "1 Chronicles": ["1chron", "1chr", "1ch"], "2 Chronicles": ["2chron", "2chr", "2ch"],
    "Ezra": ["ezr"], "Nehemiah": ["neh", "ne"], "Esther": ["esth", "est"], "Job": ["jb"],
    "Psalms": ["psalm", "ps", "psa", "pss"], "Proverbs": ["prov", "prv", "pr"],
    "Ecclesiastes": ["eccl", "ecc", "qoh"], "Song of Solomon": ["song", "sos", "canticles"],
    "Isaiah": ["isa", "is"], "Jeremiah": ["jer", "je"], "Lamentations": ["lam", "la"],
    "Ezekiel": ["ezek", "ez"], "Daniel": ["dan", "da"], "Hosea": ["hos", "ho"], "Joel": ["joe"],
    "Amos": ["am"], "Obadiah": ["obad", "ob"], "Jonah": ["jon"], "Micah": ["mic", "mi"],
    "Nahum": ["nah", "na"], "Habakkuk": ["hab"], "Zephaniah": ["zeph", "zep"], "Haggai": ["hag"],
    "Zechariah": ["zech", "zec"], "Malachi": ["mal"],
    "Matthew": ["matt", "mt"], "Mark": ["mk", "mrk"], "Luke": ["lk", "luk"], "John": ["jn", "joh"],
    "Acts": ["ac"], "Romans": ["rom", "ro"], "1 Corinthians": ["1cor", "1co"],
    "2 Corinthians": ["2cor", "2co"], "Galatians": ["gal", "ga"], "Ephesians": ["eph"],
    "Philippians": ["phil", "php"], "Colossians": ["col"], "1 Thessalonians": ["1thess", "1th"],
    "2 Thessalonians": ["2thess", "2th"], "1 Timothy": ["1tim", "1ti"], "2 Timothy": ["2tim", "2ti"],
    "Titus": ["tit"], "Philemon": ["phlm", "phm"], "Hebrews": ["heb"], "James": ["jas", "jm"],
    "1 Peter": ["1pet", "1pe"], "2 Peter": ["2pet", "2pe"], "1 John": ["1jn", "1jo", "1joh"],
    "2 John": ["2jn", "2jo"], "3 John": ["3jn", "3jo"], "Jude": ["jud"],
    "Revelation": ["rev", "rv", "apoc"],
}

# alias/canonical (normalised: lower, no spaces/dots) → canonical
_LOOKUP: dict[str, str] = {}
for _canon, _aliases in _BOOKS.items():
    _LOOKUP[_canon.lower().replace(" ", "")] = _canon
    for _a in _aliases:
        _LOOKUP[_a.replace(" ", "")] = _canon
    # also allow the full name without the leading number-space (e.g. "1john")
    _LOOKUP[_canon.lower().replace(" ", "").replace(".", "")] = _canon

# leading ordinal forms: "1", "2", "3", "I", "II", "III", "First", "Second", "Third"
_ORD = {"i": "1", "ii": "2", "iii": "3", "first": "1", "second": "2", "third": "3",
        "1": "1", "2": "2", "3": "3"}

_REF_RE = re.compile(
    r"\b(?P<ord>(?:[123]|I{1,3}|First|Second|Third)\s+)?"
    r"(?P<book>[A-Za-z]{2,})\.?\s+"
    r"(?P<chap>\d+):(?P<v1>\d+)(?:\s*[-–]\s*(?P<v2>\d+))?\b",
    re.IGNORECASE)


def _canon_book(ordinal: str | None, book: str) -> str | None:
    b = book.lower().strip()
    o = (ordinal or "").strip().lower()
    key = (_ORD.get(o, "") + b) if o else b
    return _LOOKUP.get(key) or _LOOKUP.get(b)


def canonical(book: str, chap: int, v1: int, v2: int | None = None) -> str:
    verses = f"{v1}" if not v2 or v2 == v1 else f"{v1}-{v2}"
    return f"{book} {chap}:{verses}"


def parse_refs(text: str) -> list[str]:
    """Canonical references found in `text`, de-duplicated, order-preserving."""
    out, seen = [], set()
    for m in _REF_RE.finditer(text or ""):
        book = _canon_book(m.group("ord"), m.group("book"))
        if not book:
            continue
        chap = int(m.group("chap")); v1 = int(m.group("v1"))
        v2 = int(m.group("v2")) if m.group("v2") else None
        ref = canonical(book, chap, v1, v2)
        if ref not in seen:
            seen.add(ref); out.append(ref)
    return out


def parse_refs_struct(text: str) -> list[dict]:
    """Structured refs: [{book, chap, v1, v2, ref}] for overlap matching."""
    out = []
    for m in _REF_RE.finditer(text or ""):
        book = _canon_book(m.group("ord"), m.group("book"))
        if not book:
            continue
        chap = int(m.group("chap")); v1 = int(m.group("v1"))
        v2 = int(m.group("v2")) if m.group("v2") else v1
        out.append({"book": book, "chap": chap, "v1": v1, "v2": v2,
                    "ref": canonical(book, chap, v1, None if v2 == v1 else v2)})
    return out


def refs_overlap(a: dict, b: dict) -> bool:
    """True if two structured refs are the same book+chapter and their verse ranges overlap."""
    return (a["book"] == b["book"] and a["chap"] == b["chap"]
            and a["v1"] <= b["v2"] and b["v1"] <= a["v2"])


def normalize_ref(raw: str) -> str | None:
    """Normalise a single reference string, or None if it isn't one."""
    refs = parse_refs(raw)
    return refs[0] if refs else None
