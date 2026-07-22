"""Generate the SBLGNT (modern critical-text) Greek NT interlinear + concordance, keyed to Strong's.

A parallel to gen_strongs.py, but over the *modern* critical text (SBLGNT) instead of the KJV/TR.
Keeps Strong's numbers as the shared lookup key so the existing lexicon + concordance UI still work —
the SBLGNT basis just changes which Greek word forms + morphology are shown and which verses a Strong's
number resolves to.

Data (both free / license-clean — ship a credits note):
  • MorphGNT (github.com/morphgnt/sblgnt): per-book `NN-XX-morphgnt.txt`, columns
    `ref pos parse text word normalized lemma`. SBLGNT text under the sblgnt.com license
    (CC-BY 4.0 as of 2026); morphology/lemmas CC-BY-SA 3.0. Cite: Tauber 2017, DOI 10.5281/zenodo.376200.
  • greek-lemma-mappings (github.com/jtauber/greek-lemma-mappings) `lexemes.yaml`: lemma → strongs
    (+ dodson / abbott-smith citation forms). CC-BY-SA 4.0.

Output under <vault>/AI/bible-sblgnt/ (exclude from RAG like bible-strongs):
  • {book-slug}.json  — {"<slug>.<ch>.<v>": [{g,l,m,s}, …]} (g=Greek word, l=lemma, m=readable morph, s=Strong's Gnnn)
  • _concordance-G.json — {"G<n>": ["<slug>.<ch>.<v>", …]} over the SBLGNT text

Usage:  python -m assistant_core.bible.tools.gen_sblgnt <data_dir> <vault_path>
  <data_dir> holds sblgnt/ (MorphGNT files) and glm/ (greek-lemma-mappings, with lexemes.yaml).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root, for the shared table
from assistant_core.bible import books

# SBLGNT editorial/apparatus marks (marginal-reading diamonds, half-brackets, double brackets) — strip
# them from the displayed word so the interlinear reads cleanly.
_APPARATUS = re.compile(r"[⸀-⹏⟦⟧]")

# index 0 = Matthew (booknum 40); MorphGNT ref book 01=Matthew … 27=Revelation → +39.
NT_SLUGS = books.NT_SLUGS

_POS = {"A-": "adj", "C-": "conj", "D-": "adv", "I-": "interj", "N-": "noun", "P-": "prep",
        "RA": "art", "RD": "dem", "RI": "int", "RP": "pron", "RR": "rel", "V-": "verb", "X-": "ptcl"}
_PERSON = {"1": "1", "2": "2", "3": "3"}
_TENSE = {"P": "pres", "I": "impf", "F": "fut", "A": "aor", "X": "perf", "Y": "plup"}
_VOICE = {"A": "act", "M": "mid", "P": "pass"}
_MOOD = {"I": "ind", "D": "impv", "S": "subj", "O": "opt", "N": "inf", "P": "ptcp"}
_CASE = {"N": "nom", "G": "gen", "D": "dat", "A": "acc"}
_NUMBER = {"S": "sg", "P": "pl"}
_GENDER = {"M": "masc", "F": "fem", "N": "neut"}
_DEGREE = {"C": "compar", "S": "superl"}


def decode_morph(pos: str, parse: str) -> str:
    """CCAT pos + 8-char parse code → a compact readable morphology, e.g. 'verb pres act ind 3 sg'."""
    out = [_POS.get(pos, pos.rstrip("-"))]
    p = (parse + "--------")[:8]
    for ch, table in zip(p, (_PERSON, _TENSE, _VOICE, _MOOD, _CASE, _NUMBER, _GENDER, _DEGREE)):
        if ch != "-" and ch in table:
            out.append(table[ch])
    return " ".join(out)


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: gen_sblgnt.py <data_dir> <vault_path>", file=sys.stderr)
        return 2
    data_dir, vault = Path(sys.argv[1]), Path(sys.argv[2])
    sblgnt_dir, glm = data_dir / "sblgnt", data_dir / "glm"
    if not sblgnt_dir.is_dir() or not (glm / "lexemes.yaml").exists():
        print(f"Need {sblgnt_dir}/ (MorphGNT) and {glm}/lexemes.yaml", file=sys.stderr)
        return 1

    lex = yaml.safe_load((glm / "lexemes.yaml").read_text(encoding="utf-8"))
    lemma_strongs = {lemma: f"G{props['strongs']}" for lemma, props in lex.items()
                     if isinstance(props, dict) and props.get("strongs") is not None}

    out_dir = vault / "AI" / "bible-sblgnt"
    out_dir.mkdir(parents=True, exist_ok=True)
    concordance: dict[str, list[str]] = {}
    total_words = missing_strongs = 0
    books = 0
    for f in sorted(sblgnt_dir.glob("*-morphgnt.txt")):
        book: dict[str, list[dict]] = {}
        slug = None
        for line in f.read_text(encoding="utf-8").splitlines():
            parts = line.split(" ")
            if len(parts) < 7:
                continue
            ref, pos, parse, text, _word, _norm, lemma = parts[:7]
            bb, cc, vv = int(ref[0:2]), int(ref[2:4]), int(ref[4:6])
            slug = NT_SLUGS[bb - 1]
            key = f"{slug}.{cc}.{vv}"
            strongs = lemma_strongs.get(lemma, "")
            if not strongs:
                missing_strongs += 1
            book.setdefault(key, []).append(
                {"g": _APPARATUS.sub("", text), "l": lemma, "m": decode_morph(pos, parse), "s": strongs})
            if strongs:
                concordance.setdefault(strongs, []).append(key)
            total_words += 1
        if slug:
            (out_dir / f"{slug}.json").write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
            books += 1
    (out_dir / "_concordance-G.json").write_text(json.dumps(concordance, ensure_ascii=False), encoding="utf-8")
    (out_dir / "_CREDITS.md").write_text(
        "# SBLGNT interlinear — sources & licenses\n\n"
        "- **Greek text:** The Greek New Testament: SBL Edition (SBLGNT), ed. Michael W. Holmes, "
        "© 2010 Society of Biblical Literature and Logos Bible Software — used under the sblgnt.com "
        "license (CC-BY 4.0).\n"
        "- **Morphology & lemmas:** MorphGNT: SBLGNT Edition, ed. J. K. Tauber (2017), "
        "https://github.com/morphgnt/sblgnt — CC-BY-SA 3.0 (DOI 10.5281/zenodo.376200).\n"
        "- **Lemma → Strong's mapping:** greek-lemma-mappings, J. K. Tauber, "
        "https://github.com/jtauber/greek-lemma-mappings — CC-BY-SA 4.0.\n\n"
        "Our derived data in this folder is likewise CC-BY-SA.\n", encoding="utf-8")
    print(f"SBLGNT: {total_words} words / {books} books; {len(concordance)} Strong's numbers; "
          f"{missing_strongs} words had no Strong's mapping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
