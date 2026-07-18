"""Build a chapter -> Matthew Henry note index for the LoreMaster reader.

Matthew Henry's Complete Commentary (public domain, ingested under
`AI/Library/matthew-henry/mhcNNNNN.md`) is organised one file per chapter.
Each file's H1 carries a bracketed title such as:

    Matthew Henry's Complete Commentary on the Whole Bible [Genesis, Chapter I].
    Matthew Henry's Complete Commentary on the Whole Bible [Matthew V].
    Matthew Henry's Complete Commentary on the Whole Bible [Genesis: Introduction].

This walks those files and emits `AI/bible-mhc.json`:

    { "40:5": "mhc01234", "1:1": "mhc01001", "1:0": "mhc01000", ... }

keyed by "<booknum>:<chapter>" (chapter 0 = the book Introduction) so the
plugin can look up the commentary note from the booknum it already derives
from a chapter note's path. Run it once per vault after (re)importing the
commentary:

    python -m assistant_core.bible.tools.gen_mhc_index "<vault path>"
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# MHC display book name -> canonical book number (1..66).
BOOKS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua",
    "Judges", "Ruth", "First Samuel", "Second Samuel", "First Kings",
    "Second Kings", "First Chronicles", "Second Chronicles", "Ezra",
    "Nehemiah", "Esther", "Job", "Psalms", "Proverbs", "Ecclesiastes",
    "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations", "Ezekiel",
    "Daniel", "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah", "Nahum",
    "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi", "Matthew",
    "Mark", "Luke", "John", "Acts", "Romans", "First Corinthians",
    "Second Corinthians", "Galatians", "Ephesians", "Philippians",
    "Colossians", "First Thessalonians", "Second Thessalonians",
    "First Timothy", "Second Timothy", "Titus", "Philemon", "Hebrews",
    "James", "First Peter", "Second Peter", "First John", "Second John",
    "Third John", "Jude", "Revelation",
]
BOOK_NUM = {name: i + 1 for i, name in enumerate(BOOKS)}
# Longest names first so "First Corinthians" matches before "Corinthians"-like fragments.
BOOK_NAMES_BY_LEN = sorted(BOOK_NUM, key=len, reverse=True)

TITLE = re.compile(r"Whole Bible \[(.+?)\]")
ROMAN = re.compile(r"^([IVXLCDM]+)$")


def roman_to_int(s: str) -> int:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total, prev = 0, 0
    for ch in reversed(s):
        v = vals[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def parse_title(title: str):
    """('Genesis, Chapter I' | 'Matthew V' | 'Genesis: Introduction') -> (booknum, chapter) or None."""
    t = title.strip()
    # Which book does this title start with?
    book = next((b for b in BOOK_NAMES_BY_LEN if t == b or t.startswith(b + " ")
                 or t.startswith(b + ",") or t.startswith(b + ":")), None)
    if not book:
        return None
    rest = t[len(book):].strip(" ,:")
    if not rest or rest.lower() == "introduction":
        return BOOK_NUM[book], 0
    rest = re.sub(r"^Chapter\s+", "", rest, flags=re.I).strip()
    m = ROMAN.match(rest)
    if not m:
        return None
    return BOOK_NUM[book], roman_to_int(m.group(1))


def build(vault: Path) -> dict:
    src = vault / "AI" / "Library" / "matthew-henry"
    index: dict[str, str] = {}
    for f in sorted(src.glob("mhc*.md")):
        head = f.read_text(encoding="utf-8", errors="replace")[:600]
        m = TITLE.search(head)
        if not m:
            continue
        parsed = parse_title(m.group(1))
        if not parsed:
            continue
        booknum, chapter = parsed
        index.setdefault(f"{booknum}:{chapter}", f.stem)  # first wins
    return index


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: gen_mhc_index.py <vault path>", file=sys.stderr)
        return 2
    vault = Path(sys.argv[1])
    src = vault / "AI" / "Library" / "matthew-henry"
    if not src.is_dir():
        print(f"No matthew-henry library at {src}", file=sys.stderr)
        return 1
    index = build(vault)
    out = vault / "AI" / "bible-mhc.json"
    out.write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")
    chapters = sum(1 for k in index if not k.endswith(":0"))
    intros = sum(1 for k in index if k.endswith(":0"))
    print(f"Wrote {out} — {len(index)} entries ({chapters} chapters, {intros} intros).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
