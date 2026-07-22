"""Generate the WEB Bible as structured LoreMaster notes (NOT via the flattening HTML ingest):
  bible/{NN:02d}-{slug}/web/{slug}-{CCC:03d}.md   e.g. bible/40-matthew/web/matthew-001.md
Notes carry frontmatter (cssclasses:[bible] + book/chapter/version), a clean heading, section
headings (##), italic Psalm titles, poetry stichs (em-space indent + hard breaks), ^vN anchors,
red-letter <span class="lm-wj"> (words of Christ), prev/next nav — and NO baked cross-references
(those come from the renderer's shared-data overlay). Also splits the shared cross-reference map
into per-book JSON for the renderer to load lazily.

Inputs (place beside this script, or point at them with env vars):
  BIBLE_SRC   dir holding engwebp_usfm.zip (eBible.org WEB, public domain) + cross-references.json
              (OpenBible.info topical cross-references, public domain). Default: this script's dir.
  BIBLE_VAULT target Obsidian vault root. Default: C:/development/echo-test-vault.

Run:  python -m assistant_core.bible.tools.gen_bible_notes   (with the two data files in BIBLE_SRC)
"""
import json, os, pathlib, zipfile, re, sys
from usfm_parse import parse_book

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))  # repo root, for the shared table
from assistant_core.bible import books

SC = pathlib.Path(os.environ.get("BIBLE_SRC", pathlib.Path(__file__).parent))
VAULT = pathlib.Path(os.environ.get("BIBLE_VAULT", r"C:/development/echo-test-vault"))
BIBLE = VAULT / "bible"
VERSION = "web"

# USFM 3-letter codes (the zip's book files), in canonical order. Book number + display name come
# from the shared canonical table; only the USFM code is source-specific.
USFM_ABBRS = [
 "GEN","EXO","LEV","NUM","DEU","JOS","JDG","RUT","1SA","2SA","1KI","2KI","1CH","2CH","EZR","NEH","EST",
 "JOB","PSA","PRO","ECC","SNG","ISA","JER","LAM","EZK","DAN","HOS","JOL","AMO","OBA","JON","MIC","NAM",
 "HAB","ZEP","HAG","ZEC","MAL","MAT","MRK","LUK","JHN","ACT","ROM","1CO","2CO","GAL","EPH","PHP","COL",
 "1TH","2TH","1TI","2TI","TIT","PHM","HEB","JAS","1PE","2PE","1JN","2JN","3JN","JUD","REV",
]
BOOKS = [(ab, n, t) for ab, (n, _s, t) in zip(USFM_ABBRS, books.BOOKS)]   # (USFM code, number, name)
def slug(n): return n.lower().replace(" ", "-")
INDENT = "  "   # em-spaces per poetry level (renders as indent in any viewer)

def book_dir(num, name): return BIBLE / f"{num:02d}-{slug(name)}" / VERSION
def chap_path(num, name, ch): return book_dir(num, name) / f"{slug(name)}-{ch:03d}.md"
def wikilink(num, name, ch=None):
    p = chap_path(num, name, ch) if ch else book_dir(num, name) / f"{slug(name)}.md"
    return str(p.relative_to(VAULT).with_suffix("")).replace("\\", "/")

def poetry_line(style, text):
    # keep {{wj}}/{{/wj}} sentinels here — they're balanced per-verse later (wj_balance)
    lvl = {"q1":0,"q2":1,"q3":2,"q4":3,"qr":1,"qc":0}.get(style, 0)
    return (INDENT * lvl) + text

def render_chapter(num, name, ch_blocks, ch, seq, pos):
    slg = slug(name)
    parastarts = ",".join(str(b["v"]) for b in ch_blocks if b["v"] is not None and b.get("pstart"))
    fm = ["---", "cssclasses:", "  - bible", f"bible-version: {VERSION}",
          f"bible-book: {slg}", f"bible-booknum: {num}", f"bible-chapter: {ch}",
          f"bible-parastarts: {parastarts}", "---", ""]
    out = fm + [f"# {name} {ch}", ""]
    # nav
    i = pos[(num, ch)]
    nav = [f"[[{wikilink(num, name)}|{name}]]"]
    if i > 0:
        pn, pnm, pc = seq[i-1]; nav.insert(0, f"[[{wikilink(pn, pnm, pc)}|← {pnm} {pc}]]")
    if i < len(seq)-1:
        nn, nnm, nc = seq[i+1]; nav.append(f"[[{wikilink(nn, nnm, nc)}|{nnm} {nc} →]]")
    out += [" · ".join(nav), ""]

    # Red-letter (words of Christ) runs cross verse/stich boundaries, but text was cleaned per line,
    # so {{wj}}/{{/wj}} sentinels arrive split across blocks. Convert them to <span> with a running
    # open/close state so EVERY verse's HTML is self-balanced: a still-open run is closed at the verse
    # end and re-opened at the next verse's start. Unbalanced inline HTML stops Obsidian applying the
    # class, so this balancing is what actually makes the red render.
    wj_open = [False]
    def wj_balance(text):
        result = ["<span class=\"lm-wj\">"] if wj_open[0] else []
        for tok in re.split(r"(\{\{/?wj\}\})", text):
            if tok == "{{wj}}":
                if not wj_open[0]:
                    result.append("<span class=\"lm-wj\">"); wj_open[0] = True
            elif tok == "{{/wj}}":
                if wj_open[0]:
                    result.append("</span>"); wj_open[0] = False
            else:
                result.append(tok)
        if wj_open[0]:
            result.append("</span>")   # close at verse end; re-opened next verse
        return "".join(result)

    # group blocks into verses; emit headings/titles standalone
    cur = None  # (vnum, [ (style,text) ... ])
    def flush():
        nonlocal cur
        if not cur: return
        vnum, lines = cur
        parts = [poetry_line(st, tx) for st, tx in lines]
        text = wj_balance("  \n".join(parts))   # sentinels -> balanced spans
        # hard breaks between stichs; ^vN anchor INLINE at the very end — Reading view hides it, and
        # (unlike an own-line anchor) it leaves no trailing line break for the cross-ref markers to
        # fall onto, so the overlay markers stay on the verse line and don't break the flow.
        block = f"**{vnum}** " + text + f" ^v{vnum}"
        out.append(block); out.append("")
        cur = None
    for b in ch_blocks:
        if b["style"] in ("s", "d"):
            flush()
            htxt = wj_balance(b["t"])
            out.append(f"## {htxt}" if b["style"] == "s" else f"*{htxt}*")
            out.append("")
            continue
        if b["v"] is not None:
            flush()
            cur = (b["v"], [(b["style"], b["t"])])
        elif cur:
            cur[1].append((b["style"], b["t"]))
    flush()
    return "\n".join(out).rstrip() + "\n"

def main():
    import shutil
    if BIBLE.exists(): shutil.rmtree(BIBLE)
    zf = zipfile.ZipFile(SC / "engwebp_usfm.zip")
    parsed = {}
    for code, num, name in BOOKS:
        fn = [n for n in zf.namelist() if code in n and n.endswith(".usfm")][0]
        parsed[num] = parse_book(zf.read(fn).decode("utf-8", "replace"))
    # linear chapter sequence for nav
    seq = []
    for code, num, name in BOOKS:
        for ch in sorted(parsed[num]): seq.append((num, name, ch))
    pos = {(n, c): i for i, (n, _, c) in enumerate(seq)}

    nchap = 0
    for code, num, name in BOOKS:
        book_dir(num, name).mkdir(parents=True, exist_ok=True)
        chs = sorted(parsed[num])
        for ch in chs:
            chap_path(num, name, ch).write_text(render_chapter(num, name, parsed[num][ch], ch, seq, pos), encoding="utf-8")
            nchap += 1
        # per-book MOC
        moc = ["---", "cssclasses:", "  - bible", "---", "", f"# {name}", ""]
        moc += [f"- [[{wikilink(num, name, ch)}|{name} {ch}]]" for ch in chs]
        (book_dir(num, name) / f"{slug(name)}.md").write_text("\n".join(moc) + "\n", encoding="utf-8")
    print("chapters written:", nchap)

    # master index
    mi = ["---", "cssclasses:", "  - bible", "---", "", "# Holy Bible (WEB)", "",
          "*World English Bible — public domain.*", ""]
    for code, num, name in BOOKS:
        mi.append(f"- [[{wikilink(num, name)}|{num:02d} {name}]]")
    (BIBLE / "bible.md").write_text("\n".join(mi) + "\n", encoding="utf-8")

    # split shared cross-refs into per-book JSON (renderer loads the open book's file)
    xr = json.loads((SC / "cross-references.json").read_text(encoding="utf-8"))
    perbook = {}
    for key, targets in xr.items():
        bslug = key.rsplit(".", 2)[0]
        perbook.setdefault(bslug, {})[key] = targets
    cx = VAULT / "AI" / "bible-crossrefs"; cx.mkdir(parents=True, exist_ok=True)  # shared, version-independent
    for bslug, data in perbook.items():
        (cx / f"{bslug}.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print("per-book crossref files:", len(perbook))

if __name__ == "__main__":
    main()
