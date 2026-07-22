"""One-time migration: bake a prev·book·next nav line at the BOTTOM of every generated Bible chapter
note that lacks one, so it renders as a real block right after the last verse (no reading-view gap).

Generated notes already carry a nav at the top; this adds the matching one at the bottom. Idempotent —
a note whose last non-empty line already has ← and → is skipped. (Pasted chapters bake both ends via
the plugin, so they're skipped here.) Run per vault:

    python -m assistant_core.bible.tools.add_bottom_nav "<vault path>"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root, for the shared table
from assistant_core.bible.books import book_label   # slug -> Title (canonical, e.g. "Song of Solomon")

CHAPTER_RE = re.compile(r"^(?P<slug>.+)-(?P<ch>\d+)\.md$")


def nav_line(booknum: str, slug: str, version: str, chapter: int, has_next: bool) -> str:
    base = f"bible/{booknum}-{slug}/{version}/{slug}"
    parts = []
    if chapter > 1:
        parts.append(f"[[{base}-{chapter-1:03d}|← {book_label(slug)} {chapter-1}]]")
    parts.append(f"[[{base}|{book_label(slug)}]]")
    if has_next:
        parts.append(f"[[{base}-{chapter+1:03d}|{book_label(slug)} {chapter+1} →]]")
    return " · ".join(parts)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: add_bottom_nav.py <vault path>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]) / "bible"
    if not root.is_dir():
        print(f"No bible/ folder at {root}", file=sys.stderr)
        return 1
    added = skipped = 0
    for f in root.rglob("*.md"):
        m = CHAPTER_RE.match(f.name)
        if not m:
            continue  # book MOC / bible.md — not a chapter note
        parts = f.parts
        # …/bible/{NN}-{slug}/{version}/{slug}-{CCC}.md
        try:
            booknum, book_dir = parts[-3].split("-", 1)
        except ValueError:
            continue
        slug, version, chapter = m.group("slug"), parts[-2], int(m.group("ch"))
        text = f.read_text(encoding="utf-8")
        lines = [ln for ln in text.rstrip().split("\n")]
        last = next((ln for ln in reversed(lines) if ln.strip()), "")
        if "←" in last and "→" in last:
            skipped += 1
            continue  # already has a bottom nav
        has_next = (f.parent / f"{slug}-{chapter+1:03d}.md").exists()
        nav = nav_line(booknum, slug, version, chapter, has_next)
        f.write_text(text.rstrip("\n") + "\n\n" + nav + "\n", encoding="utf-8")
        added += 1
    print(f"Bottom nav added to {added} note(s); {skipped} already had one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
