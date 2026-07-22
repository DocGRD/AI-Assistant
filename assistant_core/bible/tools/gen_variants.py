"""Find New-Testament textual variants between the Textus Receptus (KJV/Strong's) and the modern
critical text (SBLGNT) — chiefly the verses the TR/KJV includes that the critical text omits (Matt
17:21, Acts 8:37, 1 John 5:7 …), and any the critical text has that the KJV numbering doesn't.

Both datasets already ship (AI/bible-strongs/ = KJV+Strong's, AI/bible-sblgnt/ = SBLGNT), so this is a
pure comparison — no new sources. Output: AI/bible-variants/_variants.json = {"slug.ch.v": "tr-only" |
"crit-only"}. The reader marks these verses with a short textual note.

Env: BIBLE_VAULT (target vault).
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from assistant_core.bible import books

VAULT = pathlib.Path(os.environ.get("BIBLE_VAULT", r"C:/development/echo-test-vault"))
STRONGS = VAULT / "AI" / "bible-strongs"
SBLGNT = VAULT / "AI" / "bible-sblgnt"
OUT = VAULT / "AI" / "bible-variants"


def _verses(path: pathlib.Path) -> set:
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")).keys())


def main() -> int:
    if not SBLGNT.exists():
        print(f"SBLGNT data not found at {SBLGNT} — run gen_sblgnt.py first.")
        return 1
    variants: dict[str, str] = {}
    nt_slugs = [s for n, s, _ in books.BOOKS if n >= 40]
    for slug in nt_slugs:
        tr = _verses(STRONGS / f"{slug}.json")          # KJV / Textus Receptus versification
        crit = _verses(SBLGNT / f"{slug}.json")          # SBLGNT (critical) versification
        if not tr or not crit:
            continue
        for ref in tr - crit:
            variants[ref] = "tr-only"                    # in the TR/KJV, omitted by the critical text
        for ref in crit - tr:
            variants[ref] = "crit-only"                  # in the critical text, not in the KJV numbering
    OUT.mkdir(parents=True, exist_ok=True)
    # sort by canonical order for a stable, readable file
    def key(ref):
        b, c, v = ref.rsplit(".", 2)
        return (books.NUM_BY_SLUG.get(b, 999), int(c), int(v))
    ordered = {r: variants[r] for r in sorted(variants, key=key)}
    (OUT / "_variants.json").write_text(json.dumps(ordered, ensure_ascii=False, indent=0), encoding="utf-8")
    tr_only = sum(1 for v in variants.values() if v == "tr-only")
    crit_only = sum(1 for v in variants.values() if v == "crit-only")
    print(f"variants: {tr_only} TR-only (omitted by the critical text) + {crit_only} critical-only")
    for r, t in list(ordered.items())[:20]:
        print(f"  {books.TITLE_BY_SLUG.get(r.rsplit('.',2)[0])} {r.rsplit('.',2)[1]}:{r.rsplit('.',2)[2]} — {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
