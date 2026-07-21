"""Upgrade an already-generated Strong's lexicon in a vault with fuller free defs.

Adds a `d` (fuller definition) field to every entry in `AI/bible-strongs/_lexicon-G.json`
and `_lexicon-H.json` that has one:

  * Greek  → Dodson's Greek Lexicon (Public Domain, CC0). Clean modern glosses.
  * Hebrew → Brown-Driver-Briggs (Public Domain). Fuller lexical treatment.

The reader shows `d` under the short Strong's gloss (`g`) when present. Idempotent —
re-running just refreshes `d`. The source maps live in `tools/data/{dodson,bdb}-defs.json`
(built once by `data/build_maps.py` from the openscriptures/biblicalhumanities repos).

Env:
  BIBLE_VAULT   vault root (default C:/development/echo-test-vault)
"""
import os
import json
import pathlib

from gen_strongs import apply_fuller_defs  # shared merge helper

VAULT = pathlib.Path(os.environ.get("BIBLE_VAULT", r"C:/development/echo-test-vault"))
STRONGS = VAULT / "AI" / "bible-strongs"

CREDITS = """\
# Lexicon sources

The reader's Strong's popup shows two layers of definition:

- **Short gloss** — openscriptures Strong's dictionary (Public Domain).
- **Fuller definition** — for Greek, **Dodson's Greek Lexicon** (John Jackson Dodson;
  released **CC0 / Public Domain** via biblicalhumanities). For Hebrew,
  **Brown-Driver-Briggs** (BDB, 1906; Public Domain), via openscriptures HebrewLexicon,
  keyed to Strong's through its LexicalIndex.

All sources are free / public-domain and may be redistributed. Both fuller layers are
keyed to Strong's numbers; the WEB remains your reading text.
"""


def upgrade(testament: str) -> tuple[int, int]:
    path = STRONGS / f"_lexicon-{testament}.json"
    if not path.exists():
        print(f"  skip {path.name}: not found")
        return (0, 0)
    lex = json.loads(path.read_text(encoding="utf-8"))
    n = apply_fuller_defs(lex, testament)
    path.write_text(json.dumps(lex, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return (n, len(lex))


def main():
    if not STRONGS.exists():
        raise SystemExit(f"no bible-strongs data at {STRONGS}")
    g_up, g_tot = upgrade("G")
    h_up, h_tot = upgrade("H")
    (STRONGS / "_CREDITS.md").write_text(CREDITS, encoding="utf-8")
    print(f"Greek : {g_up}/{g_tot} entries gained a Dodson definition")
    print(f"Hebrew: {h_up}/{h_tot} entries gained a BDB definition")
    print(f"wrote {STRONGS}")


if __name__ == "__main__":
    main()
