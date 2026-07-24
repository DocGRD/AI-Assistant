"""Ingest the unfoldingWord Literal Text (ULT) as a word-alignment ANCHOR for the approximation engine.

The ULT (an open-licensed, form-centric update of the ASV) ships with USFM 3 word-alignment: every
English `\\w word\\w*` sits inside `\\zaln-s |x-strong="…"\\*` … `\\zaln-e\\*` milestones that carry the
original-language Strong's number. That gives us a THIRD already-tagged English anchor (register close to
formal translations like ESV/NASB), used only to widen each Strong's number's set of English surface forms
when we project onto a pasted translation. See obsidian-plugin/bible-align.ts.

Output: AI/bible-ult/{slug}.json = {"slug.ch.v": [{"e": english_word, "s": "H430"}, …]} in English order.

Encodings differ by testament (both handled):
  * Greek  x-strong="G17220"  = G + zero-padded-4 base (1722) + 1 extension digit (0)     → G1722
  * Hebrew x-strong="H0430" / "H1254a" / "b:H7225" (inseparable-prefix segments, letter homographs) → H430
The content Strong's is the LAST colon-separated segment; Hebrew letter homographs (…a/…b) collapse to
the base number to match the other anchors' unpadded keys.

Env: ULT_SRC (dir with the 66 NN-XXX.usfm files), BIBLE_VAULT (target vault).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from assistant_core.bible import books

SRC = pathlib.Path(os.environ.get("ULT_SRC", pathlib.Path(__file__).parent / "en_ult"))
VAULT = pathlib.Path(os.environ.get("BIBLE_VAULT", r"C:/development/echo-test-vault"))
OUT = VAULT / "AI" / "bible-ult"

# USFM 3-letter book codes in canonical order (1..66), zipped with the shared book table.
USFM_CODES = [
    "GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI", "1CH", "2CH",
    "EZR", "NEH", "EST", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN", "HOS",
    "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL", "MAT", "MRK", "LUK",
    "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT",
    "PHM", "HEB", "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV",
]
SLUG_BY_CODE = {code: books.SLUG_BY_NUM[i + 1] for i, code in enumerate(USFM_CODES)}

# Scan tokens in document order: chapter, verse, alignment open (with attrs), alignment close, word.
TOKEN = re.compile(
    r"\\c\s+(\d+)"                       # 1: chapter
    r"|\\v\s+(\d+)"                      # 2: verse
    r"|\\zaln-s\s+\|([^\\]*)\\\*"        # 3: alignment-start attrs
    r"|(\\zaln-e\\\*)"                   # 4: alignment-end
    r"|\\w\s+([^|\\]+?)(?:\|[^\\]*)?\\w\*"  # 5: english word
)
X_STRONG = re.compile(r'x-strong="([^"]*)"')
SEG = re.compile(r"^([GH])(\d+)([a-z]?)$")


def norm_strong(raw: str) -> str:
    """"G17220"/"b:H7225"/"H1254a" → "G1722"/"H7225"/"H1254" (base key matching the other anchors)."""
    seg = raw.strip().split(":")[-1]           # drop inseparable-prefix segments (b:/c:/d:)
    m = SEG.match(seg)
    if not m:
        return ""
    prefix, digits, _suf = m.group(1), m.group(2), m.group(3)
    n = int(digits)
    if prefix == "G" and len(digits) == 5:     # Greek: 4-digit base + 1 extension digit
        n //= 10
    return f"{prefix}{n}" if n > 0 else ""


def parse_book(text: str) -> dict:
    """USFM text → {"slug.ch.v": [{"e": word, "s": strong, "g": group}, …]} (English order).

    `g` is the ORIGINAL-WORD group: every English word under the same `\\zaln` milestone shares it, which is
    how one Greek/Hebrew word that takes several English words ("ἐν ἀρχῇ" → "in the beginning") is kept
    together. The aligner merges a run of English words sharing a group into a single link.
    """
    m = re.search(r"\\id\s+(\w+)", text)
    slug = SLUG_BY_CODE.get(m.group(1)) if m else None
    if not slug:
        return {}
    out: dict = {}
    ch = v = 0
    stack: list[tuple[str, int]] = []           # open alignments (Strong's, group id) — milestones nest
    group = 0
    for tok in TOKEN.finditer(text):
        if tok.group(1):
            ch, v = int(tok.group(1)), 0
        elif tok.group(2):
            v = int(tok.group(2))
        elif tok.group(3) is not None:
            xs = X_STRONG.search(tok.group(3))
            group += 1
            stack.append((norm_strong(xs.group(1)) if xs else "", group))
        elif tok.group(4):
            if stack:
                stack.pop()
        elif tok.group(5) is not None and ch and v:
            word = tok.group(5).strip()
            # innermost TAGGED alignment supplies both the Strong's and the original-word group
            tagged = next(((s, g) for s, g in reversed(stack) if s), ("", 0))
            if word:
                out.setdefault(f"{slug}.{ch}.{v}", []).append({"e": word, "s": tagged[0], "g": tagged[1]})
    return out


def main() -> int:
    files = sorted(SRC.glob("*.usfm"))
    if not files:
        print(f"No ULT USFM at {SRC} — clone git.door43.org/unfoldingWord/en_ult or set ULT_SRC.")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    books_done = words = tagged = 0
    for path in files:
        data = parse_book(path.read_text(encoding="utf-8"))
        if not data:
            continue
        slug = next(iter(data)).split(".")[0]
        (OUT / f"{slug}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        books_done += 1
        for ws in data.values():
            words += len(ws)
            tagged += sum(1 for w in ws if w["s"])
    (OUT / "_CREDITS.md").write_text(
        "# unfoldingWord Literal Text (ULT) — word-alignment anchor\n\n"
        "- **Text + word-level Strong's alignment:** unfoldingWord® Literal Text, "
        "https://www.unfoldingword.org/ult (Door43). Licensed **CC BY-SA 4.0**. Used here only as an "
        "alignment anchor (English surface forms per Strong's number) for the approximation engine that "
        "connects pasted translations to the original languages; the ULT text itself is not published as "
        "a reading version in this vault.\n", encoding="utf-8")
    print(f"ULT: {words} words ({tagged} Strong's-tagged) / {books_done} books → AI/bible-ult/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
