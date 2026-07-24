"""Generate the Berean Standard Bible (BSB) as a Strong's-tagged reading version + a reverse interlinear.

Source: the free BSB translation tables (bereanbible.com/bsb_tables.tsv) — one row per ORIGINAL-language
word, carrying the Hebrew/Greek word, its Strong's number + morphology, and the BSB English gloss, plus
sort columns for both original and English order. So one dataset yields:

  * bible/{NN}-{slug}/bsb/{slug}-{CCC}.md   — the BSB English reading text, every word/phrase wrapped in
    a `<span class="lm-s" data-s="Hnnnn">…</span>` so the reader's Strong's hover/tap works natively.
  * AI/bible-bsb/{slug}.json                — the REVERSE interlinear: per verse, the words in ORIGINAL
    order, each { o: original, e: English gloss, s: Strong's, m: morph, t: translit }.

Env: BSB_SRC (path to bsb_tables.tsv), BIBLE_VAULT (target vault).
"""
from __future__ import annotations

import csv
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from assistant_core.bible import books

SRC = pathlib.Path(os.environ.get("BSB_SRC", pathlib.Path(__file__).parent / "bsb_tables.tsv"))
VAULT = pathlib.Path(os.environ.get("BIBLE_VAULT", r"C:/development/echo-test-vault"))
BIBLE = VAULT / "bible"
INTER = VAULT / "AI" / "bible-bsb"
VERSION = "bsb"

SLUG_BY_TITLE = {t: s for _, s, t in books.BOOKS}
# BSB title quirks → our canonical title
TITLE_FIX = {"Song of Songs": "Song of Solomon", "Psalm": "Psalms", "Revelation of John": "Revelation"}

# column indices (from the tsv header)
C_HEBSORT, C_GRKSORT, C_BSBSORT, C_VERSE, C_LANG = 0, 1, 2, 3, 4
C_ORIG, C_TRANSLIT, C_MORPH, C_STRH, C_STRG = 5, 7, 8, 10, 11
C_VERSEID, C_PAR, C_BSB, C_PNC = 12, 15, 18, 19

_REF = re.compile(r"^(.*?)\s+(\d+):(\d+)$")


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# BSB table placeholders: the original word has NO separate English word at this position ("vvv" — its
# sense is folded into a neighbouring word, e.g. a negative particle inside "cannot"; "-" — untranslated).
# They are markers, not text: keep the original word in the interlinear (with an empty gloss) but never
# emit them into the English reading text.
PLACEHOLDERS = {"-", "vvv"}


def is_placeholder(gloss: str) -> bool:
    return gloss.strip() in PLACEHOLDERS


def nav_line(num: int, slug: str, chapter: int, last: int) -> str:
    base = lambda c: f"bible/{books.pad2(num)}-{slug}/{VERSION}/{slug}-{books.pad3(c)}"
    parts = []
    if chapter > 1:
        parts.append(f"[[{base(chapter-1)}|← {books.TITLE_BY_SLUG[slug]} {chapter-1}]]")
    parts.append(f"[[bible/{books.pad2(num)}-{slug}/{VERSION}/{slug}|{books.TITLE_BY_SLUG[slug]}]]")
    if chapter < last:
        parts.append(f"[[{base(chapter+1)}|{books.TITLE_BY_SLUG[slug]} {chapter+1} →]]")
    return " · ".join(parts)


def write_book(slug: str, num: int, chapters: dict, inter: dict):
    """chapters = {ch: {v: {read:[(sort,gloss,strong,pnc)], para:bool}}}; inter = {"slug.ch.v":[words]}."""
    last = max(chapters) if chapters else 0
    bdir = BIBLE / f"{books.pad2(num)}-{slug}" / VERSION
    bdir.mkdir(parents=True, exist_ok=True)
    for ch, verses in sorted(chapters.items()):
        parastarts = [str(v) for v in sorted(verses) if verses[v]["para"]]
        if "1" not in parastarts:
            parastarts = ["1"] + parastarts
        base = f"{slug}-{books.pad3(ch)}"
        nav = nav_line(num, slug, ch, last)
        out = ["---", "cssclasses:", "  - bible", f"bible-version: {VERSION}",
               f"bible-book: {slug}", f"bible-booknum: {num}", f"bible-chapter: {ch}",
               "bible-parastarts:", *[f"  - {p}" for p in parastarts],
               "---", "", f"# {books.TITLE_BY_SLUG[slug]} {ch}", "", f"{nav} ^nav", ""]
        for v in sorted(verses):
            words = sorted(verses[v]["read"], key=lambda w: w[0])
            spans = []
            for _sort, gloss, strong, pnc in words:
                g = gloss.strip()
                if g and not is_placeholder(g):
                    spans.append(f'<span class="lm-s" data-s="{strong}">{esc(g)}</span>' if strong else esc(g))
                if pnc.strip():
                    spans.append(esc(pnc.strip()))
            # join with spaces, but no space before punctuation
            text = ""
            for s in spans:
                if s in (",", ".", ";", ":", "!", "?", "”", "’", ")", "—"):
                    text += s
                else:
                    text += (" " if text else "") + s
            out.append(f"**{v}** {text.strip()} ^v{v}")
            out.append("")
        out.append(f"![[{base}#^nav]]")
        (bdir / f"{base}.md").write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    INTER.mkdir(parents=True, exist_ok=True)
    import json
    # sort each verse's words into ORIGINAL-language order (Heb/Greek sort), dropping the sort key
    ordered = {k: [w for _s, w in sorted(v, key=lambda x: x[0])] for k, v in inter.items()}
    (INTER / f"{slug}.json").write_text(json.dumps(ordered, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    if not SRC.exists():
        print(f"BSB tables not found at {SRC} — download bereanbible.com/bsb_tables.tsv or set BSB_SRC.")
        return 1
    INTER.mkdir(parents=True, exist_ok=True)
    cur_slug = cur_num = None
    chapters: dict = {}
    inter: dict = {}
    ref_book = ref_ch = ref_v = None
    books_done = words = 0
    with open(SRC, encoding="utf-8") as f:
        r = csv.reader(f, delimiter="\t")
        next(r)
        for row in r:
            if len(row) <= C_PNC:
                row = row + [""] * (C_PNC + 1 - len(row))
            vid = row[C_VERSEID].strip()
            if vid:
                m = _REF.match(vid)
                if m:
                    title = TITLE_FIX.get(m.group(1), m.group(1))
                    ref_book, ref_ch, ref_v = title, int(m.group(2)), int(m.group(3))
            if ref_book is None:
                continue
            slug = SLUG_BY_TITLE.get(ref_book)
            if not slug:
                slug2 = ref_book.lower().replace(" ", "-")
                slug = slug2 if slug2 in books.NUM_BY_SLUG else None
            if not slug:
                continue
            num = books.NUM_BY_SLUG[slug]
            if slug != cur_slug:
                if cur_slug:
                    write_book(cur_slug, cur_num, chapters, inter)
                    books_done += 1
                cur_slug, cur_num, chapters, inter = slug, num, {}, {}
            lang = row[C_LANG].strip()
            strong = ""
            if lang == "Hebrew" and row[C_STRH].strip():
                strong = "H" + row[C_STRH].strip()
            elif lang == "Greek" and row[C_STRG].strip():
                strong = "G" + row[C_STRG].strip()
            gloss = row[C_BSB]
            pnc = row[C_PNC]
            try:
                sort = int(row[C_BSBSORT] or 0)
            except ValueError:
                sort = 0
            ver = chapters.setdefault(ref_ch, {}).setdefault(ref_v, {"read": [], "para": False})
            ver["read"].append((sort, gloss, strong, pnc))
            if row[C_PAR].strip():
                ver["para"] = True
            key = f"{slug}.{ref_ch}.{ref_v}"
            try:
                osort = int((row[C_HEBSORT] if lang == "Hebrew" else row[C_GRKSORT]) or 0)
            except ValueError:
                osort = 0
            inter.setdefault(key, []).append((osort, {
                # placeholder gloss → empty: the original word is real, it just has no English word of
                # its own here (the interlinear shows it with a blank English cell).
                "o": row[C_ORIG].strip(), "e": "" if is_placeholder(gloss) else gloss.strip(), "s": strong,
                "m": row[C_MORPH].strip(), "t": row[C_TRANSLIT].strip()}))
            words += 1
    if cur_slug:
        write_book(cur_slug, cur_num, chapters, inter)
        books_done += 1
    (INTER / "_CREDITS.md").write_text(
        "# BSB (Berean Standard Bible) — sources & licenses\n\n"
        "- **Text + word-level Strong's/morphology:** the Berean Standard Bible translation tables, "
        "https://berean.bible/ (Bible Hub). The BSB is freely licensed for reuse. Keyed to Strong's "
        "numbers, so it reuses the shared lexicon in `AI/bible-strongs/`.\n", encoding="utf-8")
    print(f"BSB: {words} words / {books_done} books → reading notes in bible/*/bsb/ + reverse interlinear in AI/bible-bsb/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
