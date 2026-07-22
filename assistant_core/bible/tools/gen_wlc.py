"""Generate the Hebrew Old Testament study layer (WLC + OSHB morphology) — the OT counterpart to
gen_sblgnt.py, so the reader's interlinear / concordance work on the actual Hebrew like they do on the
modern-critical Greek NT.

Source: OpenScriptures morphhb (Westminster Leningrad Codex + OSHB morphology), CC-BY 4.0. Each verse is
`<verse osisID="Gen.1.1"><w lemma="b/7225" morph="HR/Ncfsa" id="…">בְּ/רֵאשִׁ֖ית</w> …</verse>`. A word is a
compound of `/`-separated morphemes (prefixes/content/suffix); the lemma carries Strong's numbers, the
morph carries OSHB codes (a language char H/A, then per-segment part-of-speech + features).

Output under AI/bible-wlc/ (keyed to Strong's, so it reuses the existing Hebrew lexicon):
  {slug}.json            {"slug.ch.v": [{h: hebrew word, m: readable morph, s: "Hnnnn"}]}
  _concordance-H.json    {strong: [refs]}   — every verse that uses a Hebrew Strong's number
  _CREDITS.md

Env: WLC_SRC (dir with wlc/*.xml; default: a sibling `morphhb/` checkout), BIBLE_VAULT (target vault).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))  # repo root, for the shared table
from assistant_core.bible import books

SRC = pathlib.Path(os.environ.get("WLC_SRC", pathlib.Path(__file__).parent / "morphhb"))
VAULT = pathlib.Path(os.environ.get("BIBLE_VAULT", r"C:/development/echo-test-vault"))
OUT = VAULT / "AI" / "bible-wlc"

# OSIS book codes (the wlc/*.xml files) in canonical OT order → the canonical slugs (books 1..39).
OSIS_ORDER = [
    "Gen", "Exod", "Lev", "Num", "Deut", "Josh", "Judg", "Ruth", "1Sam", "2Sam", "1Kgs", "2Kgs",
    "1Chr", "2Chr", "Ezra", "Neh", "Esth", "Job", "Ps", "Prov", "Eccl", "Song", "Isa", "Jer", "Lam",
    "Ezek", "Dan", "Hos", "Joel", "Amos", "Obad", "Jonah", "Mic", "Nah", "Hab", "Zeph", "Hag", "Zech", "Mal",
]
OSIS_TO_SLUG = {osis: books.SLUG_BY_NUM[i + 1] for i, osis in enumerate(OSIS_ORDER)}

# ── OSHB morphology decode tables (from openscriptures morphhb MorphologyParser.js) ──
_POS = {"A": "adj", "C": "conj", "D": "adv", "N": "noun", "P": "pron", "R": "prep", "S": "suffix",
        "T": "part", "V": "verb"}
_NOUN_TYPE = {"c": "", "g": "gentilic", "p": "proper", "x": ""}
_ADJ_TYPE = {"a": "", "c": "cardinal", "g": "gentilic", "o": "ordinal", "x": ""}
_PRON_TYPE = {"d": "demonstrative", "f": "indefinite", "i": "interrogative", "p": "personal", "r": "relative", "x": ""}
_SUFFIX_TYPE = {"d": "directional-he", "h": "paragogic-he", "n": "paragogic-nun", "p": "pronominal", "x": ""}
_PART_TYPE = {"a": "affirmation", "d": "article", "e": "exhortation", "i": "interrogative", "j": "interjection",
              "m": "demonstrative", "n": "negative", "o": "object-marker", "p": "article+prep", "r": "relative"}
_PREP_TYPE = {"d": "article"}
_STEM_H = {"q": "qal", "N": "niphal", "p": "piel", "P": "pual", "h": "hiphil", "H": "hophal", "t": "hithpael",
           "o": "polel", "O": "polal", "r": "hithpolel", "m": "poel", "M": "poal", "k": "palel", "K": "pulal",
           "Q": "qal-pass", "l": "pilpel", "L": "polpal", "f": "hithpalpel", "D": "nithpael", "j": "pealal",
           "i": "pilel", "u": "hothpaal", "c": "tiphil", "v": "hishtaphel", "w": "nithpalel", "y": "nithpoel",
           "z": "hithpoel", "x": ""}
_STEM_A = {"q": "peal", "Q": "peil", "u": "hithpeel", "N": "niphal", "p": "pael", "P": "ithpaal", "M": "hithpaal",
           "a": "aphel", "h": "haphel", "s": "saphel", "e": "shaphel", "H": "hophal", "i": "ithpeel", "t": "hishtaphel",
           "v": "ishtaphel", "w": "hithaphel", "o": "polel", "z": "ithpoel", "r": "hithpolel", "f": "hithpalpel",
           "b": "hephal", "c": "tiphel", "m": "poel", "l": "palpel", "L": "ithpalpel", "O": "ithpolel", "G": "ittaphal", "x": ""}
_ASPECT = {"a": "inf-abs", "c": "inf-con", "h": "cohort", "i": "impf", "j": "juss", "p": "perf", "q": "seq-perf",
           "r": "ptcp-act", "s": "ptcp-pass", "v": "impv", "w": "seq-impf", "x": ""}
_GENDER = {"b": "both", "c": "com", "f": "fem", "m": "masc", "x": ""}
_NUMBER = {"d": "dual", "p": "pl", "s": "sg", "x": ""}
_STATE = {"a": "abs", "c": "con", "d": "det"}


def _feat(seq, out):
    """Append gender/number/state from a code tail (seq of remaining chars) to out."""
    tables = (_GENDER, _NUMBER, _STATE)
    for ch, table in zip(seq, tables):
        v = table.get(ch)
        if v:
            out.append(v)


def decode_seg(seg: str, aramaic: bool) -> str:
    """Decode one OSHB segment code (part-of-speech + features) → compact readable morphology."""
    if not seg:
        return ""
    pos = seg[0]
    out = [_POS.get(pos, pos)]
    rest = seg[1:]
    if pos == "N" and rest:
        t = _NOUN_TYPE.get(rest[0], "")
        if t:
            out.append(t)
        _feat(rest[1:], out)
    elif pos == "A" and rest:
        t = _ADJ_TYPE.get(rest[0], "")
        if t:
            out.append(t)
        _feat(rest[1:], out)
    elif pos == "V" and rest:
        out.append((_STEM_A if aramaic else _STEM_H).get(rest[0], ""))
        if len(rest) > 1:
            asp = _ASPECT.get(rest[1], "")
            if asp:
                out.append(asp)
            tail = rest[2:]
            if asp in ("ptcp-act", "ptcp-pass"):        # participle: gender number state
                _feat(tail, out)
            else:                                        # finite: person gender number [state]
                if tail and tail[0] in "123":
                    out.append(tail[0]); tail = tail[1:]
                _feat(tail, out)
    elif pos == "P" and rest:
        t = _PRON_TYPE.get(rest[0], "")
        if t:
            out.append(t)
        tail = rest[1:]
        if tail and tail[0] in "123":
            out.append(tail[0]); tail = tail[1:]
        _feat(tail, out)
    elif pos == "S" and rest:
        t = _SUFFIX_TYPE.get(rest[0], "")
        if t:
            out.append(t)
        tail = rest[1:]
        if tail and tail[0] in "123":
            out.append(tail[0]); tail = tail[1:]
        _feat(tail, out)
    elif pos == "T" and rest:
        t = _PART_TYPE.get(rest[0], "")
        if t:
            out.append(t)
    elif pos == "R" and rest:
        if _PREP_TYPE.get(rest[0]):
            out.append(_PREP_TYPE[rest[0]])
    return " ".join(w for w in out if w)


_NS = "{http://www.bibletechnologies.net/2003/OSIS/namespace}"


def strong_and_morph(lemma: str, morph: str):
    """From a <w> lemma + morph, return (strongs 'Hnnnn' or None, readable morph of the content segment)."""
    lemma_segs = [s.strip() for s in (lemma or "").split("/")]
    aramaic = (morph[:1] == "A")
    morph_segs = (morph[1:] if morph[:1] in ("H", "A") else morph).split("/")
    # content = first purely-numeric lemma segment (prefixes are letters; augment like "1254 a" → 1254)
    content_i, strong = None, None
    for i, seg in enumerate(lemma_segs):
        m = re.match(r"^(\d+)", seg)
        if m:
            content_i, strong = i, m.group(1)
            break
    seg_code = morph_segs[content_i] if (content_i is not None and content_i < len(morph_segs)) else \
        (morph_segs[-1] if morph_segs else "")
    return (f"H{strong}" if strong else None), decode_seg(seg_code, aramaic)


def main() -> int:
    if not (SRC / "wlc").exists():
        print(f"WLC source not found at {SRC/'wlc'} — clone github.com/openscriptures/morphhb or set WLC_SRC.")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    concordance: dict[str, list] = {}
    total_words = total_books = missing = 0
    for osis in OSIS_ORDER:
        xmlpath = SRC / "wlc" / f"{osis}.xml"
        if not xmlpath.exists():
            print(f"  (missing {xmlpath.name})"); continue
        slug = OSIS_TO_SLUG[osis]
        tree = ET.parse(xmlpath)
        book: dict[str, list] = {}
        for verse in tree.iter(f"{_NS}verse"):
            osis_id = verse.get("osisID", "")
            parts = osis_id.split(".")
            if len(parts) != 3:
                continue
            _, ch, vv = parts
            words = []
            seen = set()
            for w in verse.iter(f"{_NS}w"):
                heb = "".join(w.itertext()).strip()
                if not heb:
                    continue
                strong, morph = strong_and_morph(w.get("lemma", ""), w.get("morph", ""))
                words.append({"h": heb, "m": morph, "s": strong or ""})
                total_words += 1
                if strong:
                    if strong not in seen:
                        concordance.setdefault(strong, []).append(f"{slug}.{ch}.{vv}")
                        seen.add(strong)
                else:
                    missing += 1
            if words:
                book[f"{slug}.{ch}.{vv}"] = words
        (OUT / f"{slug}.json").write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
        total_books += 1
    (OUT / "_concordance-H.json").write_text(json.dumps(concordance, ensure_ascii=False), encoding="utf-8")
    (OUT / "_CREDITS.md").write_text(
        "# Hebrew OT interlinear — sources & licenses\n\n"
        "- **Hebrew text + morphology:** OpenScriptures Hebrew Bible (OSHB) — the Westminster Leningrad "
        "Codex with morphology, https://github.com/openscriptures/morphhb — **CC-BY 4.0**.\n"
        "- **Lexicon (glosses / lemmas):** the openscriptures Hebrew Strong's dictionary + Brown-Driver-"
        "Briggs, shared with `AI/bible-strongs/_lexicon-H.json` (Public Domain).\n\n"
        "Keyed to Strong's numbers; the WEB stays your reading text. Derived data here is CC-BY 4.0.\n",
        encoding="utf-8")
    print(f"WLC: {total_words} words / {total_books} books; {len(concordance)} Strong's numbers; "
          f"{missing} words had no Strong's.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
