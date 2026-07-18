"""Generate the KJV as LoreMaster Bible notes WITH inline Strong's, so the reader can pop up the
Strong's number + original Hebrew/Greek word on hover/tap of any tagged word.

  bible/{NN:02d}-{slug}/kjv/{slug}-{CCC:03d}.md

Each Strong's-tagged KJV phrase is wrapped `<span class="lm-s" data-s="H430">God</span>` (multiple
codes space-separated). The plugin (bible-strongs.ts) turns these into hover/tap popups → lexicon
entry. Unlike WEB (whose USFM Strong's tags are corrupt), the KJV+Strong's alignment is accurate, so
KJV is the "tap-a-word-for-Strong's" reading version; WEB stays the clean base.

Source: kaiserlik/kjv per-book JSON (`en` = KJV text with inline [Hnnnn] codes) in BIBLE_SRC/kjv/.
Reuses BOOKS + iter_en from gen_strongs.py (same dir).
"""
from __future__ import annotations

import os, pathlib, re
from gen_strongs import BOOKS, iter_en

VAULT = pathlib.Path(os.environ.get("BIBLE_VAULT", r"C:/development/echo-test-vault"))
SC = pathlib.Path(os.environ.get("BIBLE_SRC", pathlib.Path(__file__).parent))
BIBLE = VAULT / "bible"
VERSION = "kjv"

# display names, in canonical order
DISPLAY = {
    "genesis":"Genesis","exodus":"Exodus","leviticus":"Leviticus","numbers":"Numbers",
    "deuteronomy":"Deuteronomy","joshua":"Joshua","judges":"Judges","ruth":"Ruth","1-samuel":"1 Samuel",
    "2-samuel":"2 Samuel","1-kings":"1 Kings","2-kings":"2 Kings","1-chronicles":"1 Chronicles",
    "2-chronicles":"2 Chronicles","ezra":"Ezra","nehemiah":"Nehemiah","esther":"Esther","job":"Job",
    "psalms":"Psalms","proverbs":"Proverbs","ecclesiastes":"Ecclesiastes","song-of-solomon":"Song of Solomon",
    "isaiah":"Isaiah","jeremiah":"Jeremiah","lamentations":"Lamentations","ezekiel":"Ezekiel","daniel":"Daniel",
    "hosea":"Hosea","joel":"Joel","amos":"Amos","obadiah":"Obadiah","jonah":"Jonah","micah":"Micah","nahum":"Nahum",
    "habakkuk":"Habakkuk","zephaniah":"Zephaniah","haggai":"Haggai","zechariah":"Zechariah","malachi":"Malachi",
    "matthew":"Matthew","mark":"Mark","luke":"Luke","john":"John","acts":"Acts","romans":"Romans",
    "1-corinthians":"1 Corinthians","2-corinthians":"2 Corinthians","galatians":"Galatians","ephesians":"Ephesians",
    "philippians":"Philippians","colossians":"Colossians","1-thessalonians":"1 Thessalonians",
    "2-thessalonians":"2 Thessalonians","1-timothy":"1 Timothy","2-timothy":"2 Timothy","titus":"Titus",
    "philemon":"Philemon","hebrews":"Hebrews","james":"James","1-peter":"1 Peter","2-peter":"2 Peter",
    "1-john":"1 John","2-john":"2 John","3-john":"3 John","jude":"Jude","revelation":"Revelation",
}
SEQ = [(num, slug, DISPLAY[slug]) for _, num, slug in BOOKS]
POS = {num: i for i, (num, _, _) in enumerate(SEQ)}

CODES = re.compile(r"\[([HG]\d+)\]")
TAGGED = re.compile(r"([^\[\]<>]+)((?:\[[HG]\d+\])+)")


def book_dir(num, slug): return BIBLE / f"{num:02d}-{slug}" / VERSION
def chap_path(num, slug, ch): return book_dir(num, slug) / f"{slug}-{ch:03d}.md"
def wl(num, slug, ch=None):
    p = chap_path(num, slug, ch) if ch else book_dir(num, slug) / f"{slug}.md"
    return str(p.relative_to(VAULT).with_suffix("")).replace("\\", "/")


def render_verse_html(en: str) -> str:
    """KJV `en` (text with inline [Hnnnn] codes) → reading HTML with tagged phrases wrapped in
    `<span class="lm-s" data-s="…">`. Non-tagged text (and KJV <em> italics) is kept as-is."""
    en = en.replace("[[", "").replace("]]", "")
    def repl(m):
        phrase, group = m.group(1), m.group(2)
        codes = " ".join(CODES.findall(group))
        return f'<span class="lm-s" data-s="{codes}">{phrase}</span>'
    html = TAGGED.sub(repl, en)
    # Drop any orphan codes with no English word before them (leading untranslated particles like
    # [G1161] "de") so they don't show as literal "[G1161]" text.
    html = CODES.sub("", html)
    return html.strip()


def main():
    import shutil
    nchap = 0
    for _abbr, num, slug in BOOKS:
        text = (SC / "kjv" / f"{_abbr}.json").read_text(encoding="utf-8")
        chapters: dict[int, list] = {}
        for ch, v, en in iter_en(text):
            chapters.setdefault(ch, []).append((v, render_verse_html(en)))
        d = book_dir(num, slug)
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
        name = DISPLAY[slug]
        for ch in sorted(chapters):
            i = POS[num]
            nav = [f"[[{wl(num, slug)}|{name}]]"]
            if ch > 1:
                nav.insert(0, f"[[{wl(num, slug, ch-1)}|← {name} {ch-1}]]")
            elif i > 0:
                pn, ps, pnm = SEQ[i-1]; nav.insert(0, f"[[{wl(pn, ps)}|← {pnm}]]")
            if ch < max(chapters):
                nav.append(f"[[{wl(num, slug, ch+1)}|{name} {ch+1} →]]")
            elif i < len(SEQ)-1:
                nn, ns, nnm = SEQ[i+1]; nav.append(f"[[{wl(nn, ns)}|{nnm} →]]")
            out = ["---", "cssclasses:", "  - bible", f"bible-version: {VERSION}",
                   f"bible-book: {slug}", f"bible-booknum: {num}", f"bible-chapter: {ch}",
                   "bible-parastarts: 1", "---", "", f"# {name} {ch}", "",
                   " · ".join(nav), ""]
            for v, html in sorted(chapters[ch]):
                out.append(f"**{v}** {html} ^v{v}"); out.append("")
            chap_path(num, slug, ch).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
            nchap += 1
        moc = ["---", "cssclasses:", "  - bible", "---", "", f"# {name} (KJV)", ""]
        moc += [f"- [[{wl(num, slug, ch)}|{name} {ch}]]" for ch in sorted(chapters)]
        (d / f"{slug}.md").write_text("\n".join(moc) + "\n", encoding="utf-8")
    print("KJV chapters written:", nchap)


if __name__ == "__main__":
    main()
