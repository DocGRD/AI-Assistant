"""Add the root/derivation field (`r`) to an already-generated vault lexicon.

The openscriptures Strong's dictionaries carry a `derivation` string — the word's etymology / root, e.g.
G26 ἀγάπη → "from G25 (ἀγαπάω)". Earlier lexicon builds dropped it. This patches
`AI/bible-strongs/_lexicon-G.json` and `_lexicon-H.json` in place, adding `r` where a derivation exists,
so the reader's word popup can show the root. Idempotent.

Env: BIBLE_VAULT (target vault), STRONGS_SRC (dir with strongs-greek.js / strongs-hebrew.js).
"""
from __future__ import annotations

import json
import os
import pathlib

VAULT = pathlib.Path(os.environ.get("BIBLE_VAULT", r"C:/development/echo-test-vault"))
SRC = pathlib.Path(os.environ.get("STRONGS_SRC", "."))
OUT = VAULT / "AI" / "bible-strongs"


def derivations(path: pathlib.Path) -> dict:
    """openscriptures `var strongs…Dictionary = {…};` → {strong: derivation-text}."""
    txt = path.read_text(encoding="utf-8")
    obj = txt[txt.index("{", txt.index("=")): txt.rindex("}") + 1]
    out = {}
    for s, d in json.loads(obj).items():
        r = (d.get("derivation") or "").strip().rstrip(";").strip()
        if r:
            out[s] = r
    return out


def patch(lex_path: pathlib.Path, src: pathlib.Path) -> tuple[int, int]:
    if not lex_path.exists() or not src.exists():
        return (0, 0)
    lex = json.loads(lex_path.read_text(encoding="utf-8"))
    roots = derivations(src)
    added = 0
    for s, entry in lex.items():
        if s in roots and entry.get("r") != roots[s]:
            entry["r"] = roots[s]
            added += 1
    lex_path.write_text(json.dumps(lex, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return (added, len(lex))


def main() -> int:
    g_add, g_tot = patch(OUT / "_lexicon-G.json", SRC / "strongs-greek.js")
    h_add, h_tot = patch(OUT / "_lexicon-H.json", SRC / "strongs-hebrew.js")
    print(f"roots added: {g_add}/{g_tot} Greek, {h_add}/{h_tot} Hebrew → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
