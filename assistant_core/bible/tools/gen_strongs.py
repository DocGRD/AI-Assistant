"""Build the Strong's study data (interlinear + concordance + lexicon) the reader overlays.

Kept as sidecar data (like cross-references) so the Bible notes stay clean, portable markdown:
  AI/bible-strongs/{book}.json          per-book interlinear: {"book.ch.v": [[phrase, [strongs]], ...]}
  AI/bible-strongs/_concordance-H.json  Hebrew (OT): {strong: [refs...]}  — every verse using a number
  AI/bible-strongs/_concordance-G.json  Greek  (NT): {strong: [refs...]}
  AI/bible-strongs/_words.json          English (KJV) head-word -> [strongs]  (word-based search)
  AI/bible-strongs/_lexicon-H.json      {strong: {l: lemma, t: translit, g: gloss}}  (Hebrew)
  AI/bible-strongs/_lexicon-G.json      {strong: {l, t, g}}                            (Greek)

Sources (public domain):
  * KJV+Strong's — kaiserlik/kjv per-book JSON (each verse `en` is KJV text with inline `[Hnnnn]`
    codes). This is the accurate, canonical Strong's tagging (the WEB USFM's own tags are corrupt).
    Reading text stays WEB; this data powers the concordance + a per-verse interlinear panel.
  * openscriptures Strong's dictionaries (strongs-hebrew.js / strongs-greek.js) — lemma + gloss.

Inputs via env (default: this script's dir / the WEB test vault):
  BIBLE_SRC   dir with kjv/<Abbr>.json (kaiserlik) + strongs-hebrew.js + strongs-greek.js
  BIBLE_VAULT target vault root
"""
from __future__ import annotations

import json, os, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))  # repo root, for the shared table
from assistant_core.bible import books

SC = pathlib.Path(os.environ.get("BIBLE_SRC", pathlib.Path(__file__).parent))
VAULT = pathlib.Path(os.environ.get("BIBLE_VAULT", r"C:/development/echo-test-vault"))
OUT = VAULT / "AI" / "bible-strongs"

# kaiserlik/KJV source-file abbreviations, in canonical order (gen_strongs reads kjv/<Abbr>.json).
# The book number + slug come from the shared canonical table; only the abbreviation is source-specific.
KJV_ABBRS = [
 "Gen","Exo","Lev","Num","Deu","Jos","Jdg","Rth","1Sa","2Sa","1Ki","2Ki","1Ch","2Ch","Ezr","Neh","Est",
 "Job","Psa","Pro","Ecc","Sng","Isa","Jer","Lam","Eze","Dan","Hos","Joe","Amo","Oba","Jon","Mic","Nah",
 "Hab","Zep","Hag","Zec","Mal","Mat","Mar","Luk","Jhn","Act","Rom","1Co","2Co","Gal","Eph","Phl","Col",
 "1Th","2Th","1Ti","2Ti","Tit","Phm","Heb","Jas","1Pe","2Pe","1Jo","2Jo","3Jo","Jde","Rev",
]
BOOKS = [(ab, n, s) for ab, (n, s, _t) in zip(KJV_ABBRS, books.BOOKS)]   # (abbr, number, slug)
NUM = books.NUM_BY_SLUG
CODES = re.compile(r"\[([HG]\d+)\]")
SEG = re.compile(r"((?:\[[HG]\d+\])+)")
TAGS = re.compile(r"<[^>]+>")
# Pull (verse-key, en-string) pairs straight from the raw text. Some source files have malformed
# JSON in the non-English (bg/ch) fields, so we never full-parse them — we only need `en`.
VERSE_RE = re.compile(r'"([^"]+\|\d+\|\d+)"\s*:\s*\{\s*"en"\s*:\s*"((?:[^"\\]|\\.)*)"')


def iter_en(book_text: str):
    """Yield (chapter:int, verse:int, en:str) for each verse of the file's OWN book. Some source
    files have a second book's JSON concatenated after the first; a whole-file regex would pick those
    up too and mis-key them, so we lock onto the book-name of the first verse and skip the rest."""
    matches = VERSE_RE.findall(book_text)
    if not matches:
        return
    own = matches[0][0].rsplit("|", 2)[0]            # e.g. "Gen" / "1 Samuel"
    seen_refs: set = set()
    for key, body in matches:
        parts = key.split("|")
        if "|".join(parts[:-2]) != own:
            continue                                  # a concatenated foreign book — skip
        try:
            ch, v = int(parts[-2]), int(parts[-1])
        except ValueError:
            continue
        if (ch, v) in seen_refs:                      # guard against in-file duplication
            continue
        seen_refs.add((ch, v))
        yield ch, v, json.loads('"' + body + '"')     # unescape the JSON string body


def parse_en(en: str):
    """KJV verse text with inline [Hnnnn] codes -> ([[phrase,[strongs]], ...], [all strongs in order])."""
    en = TAGS.sub("", en).replace("[[", "").replace("]]", "")   # drop <em> italics + KJV title braces
    parts = SEG.split(en)                       # text, codegroup, text, codegroup, ...
    inter, alls = [], []
    i = 0
    while i < len(parts):
        text = parts[i].strip()
        codes = CODES.findall(parts[i + 1]) if i + 1 < len(parts) else []
        if text or codes:
            inter.append([text, codes])
            alls.extend(codes)
        i += 2
    return inter, alls


def head_word(phrase: str) -> str:
    """The last alphabetic word of a KJV phrase — the word a trailing Strong's code really tags
    (`In the beginning`[H7225] -> 'beginning')."""
    ws = re.findall(r"[A-Za-z]+", phrase.lower())
    return ws[-1] if ws else ""


def load_lexicon(path: pathlib.Path) -> dict:
    """openscriptures `var strongs...Dictionary = {...};` -> {strong: {l,t,g}}."""
    txt = path.read_text(encoding="utf-8")
    obj = txt[txt.index("{", txt.index("=")): txt.rindex("}") + 1]
    out = {}
    for s, d in json.loads(obj).items():
        gloss = (d.get("strongs_def") or d.get("kjv_def") or "").strip()
        out[s] = {"l": d.get("lemma", ""), "t": d.get("xlit") or d.get("translit") or "", "g": gloss}
    return out


DATA = pathlib.Path(__file__).parent / "data"


def apply_fuller_defs(lex: dict, testament: str) -> int:
    """Add a fuller free-lexicon definition (`d`) to each entry that has one.

    Greek → Dodson (CC0); Hebrew → Brown-Driver-Briggs (public domain). Keyed by
    the unpadded Strong's number. Idempotent; safe if the data files are absent.
    """
    fname = "dodson-defs.json" if testament == "G" else "bdb-defs.json"
    path = DATA / fname
    if not path.exists():
        return 0
    defs = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for strong, entry in lex.items():
        num = strong[1:].lstrip("0") or "0"  # "G2316" -> "2316"
        d = defs.get(num)
        if d:
            entry["d"] = d
            n += 1
    return n


def ref_sort_key(ref: str):
    b, c, v = ref.rsplit(".", 2)
    return (NUM.get(b, 999), int(c), int(v))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conc_h: dict[str, list] = {}
    conc_g: dict[str, list] = {}
    words: dict[str, set] = {}
    total = 0

    for abbr, num, slug in BOOKS:
        text = (SC / "kjv" / f"{abbr}.json").read_text(encoding="utf-8")
        interlinear: dict[str, list] = {}
        for ch, v, en in iter_en(text):
            ref = f"{slug}.{ch}.{v}"
            inter, alls = parse_en(en)
            interlinear[ref] = inter
            total += len(alls)
            seen = set()
            for s in alls:
                conc = conc_h if s.startswith("H") else conc_g
                if s not in seen:
                    conc.setdefault(s, []).append(ref); seen.add(s)
            for phrase, codes in inter:
                hw = head_word(phrase)
                if hw and codes:
                    words.setdefault(hw, set()).update(codes)
        (OUT / f"{slug}.json").write_text(json.dumps(interlinear, separators=(",", ":")), encoding="utf-8")

    for name, conc in (("H", conc_h), ("G", conc_g)):
        for s in conc:
            conc[s].sort(key=ref_sort_key)
        (OUT / f"_concordance-{name}.json").write_text(json.dumps(conc, separators=(",", ":")), encoding="utf-8")
    (OUT / "_words.json").write_text(
        json.dumps({w: sorted(s) for w, s in words.items()}, separators=(",", ":")), encoding="utf-8")

    lex_h = load_lexicon(SC / "strongs-hebrew.js")
    lex_g = load_lexicon(SC / "strongs-greek.js")
    up_h = apply_fuller_defs(lex_h, "H")
    up_g = apply_fuller_defs(lex_g, "G")
    (OUT / "_lexicon-H.json").write_text(json.dumps(lex_h, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    (OUT / "_lexicon-G.json").write_text(json.dumps(lex_g, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

    print(f"books: 66  tagged tokens: {total}")
    print(f"concordance: {len(conc_h)} Hebrew + {len(conc_g)} Greek numbers")
    print(f"word index: {len(words)} KJV head-words")
    print(f"lexicon: {len(lex_h)} Hebrew + {len(lex_g)} Greek entries")
    print(f"fuller defs: {up_g} Greek (Dodson) + {up_h} Hebrew (BDB)")


if __name__ == "__main__":
    main()
