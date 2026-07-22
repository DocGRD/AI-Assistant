"""Migration: link each generated Bible chapter's top & bottom nav.

The top nav line gets a `^nav` block id; the bottom nav becomes a transclusion `![[<basename>#^nav]]`
of it — so editing the top nav updates the bottom automatically, and the bottom renders on its own
line. Idempotent. Run per vault:

    python link_nav.py "<vault path>"
"""
import pathlib
import sys


def is_nav(line: str) -> bool:
    l = line.strip()
    return "[[" in l and " · " in l and "→" in l


def migrate_note(note: pathlib.Path) -> bool:
    stem = note.stem
    if "-" not in stem or not stem.rsplit("-", 1)[1].isdigit():
        return False                                   # skip book MOCs / odd names
    raw = note.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    top_i = next((i for i, l in enumerate(lines) if is_nav(l)), None)
    if top_i is None:
        return False                                   # no nav to link
    if not lines[top_i].rstrip().endswith("^nav"):
        lines[top_i] = lines[top_i].rstrip() + " ^nav"
    embed = f"![[{stem}#^nav]]"
    if not any(l.strip() == embed for l in lines):     # not already migrated
        bot_i = next((i for i in range(len(lines) - 1, -1, -1) if i != top_i and is_nav(lines[i])), None)
        if bot_i is not None:
            lines[bot_i] = embed
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", embed]
    new = nl.join(lines) + nl
    if new != raw:
        note.write_text(new, encoding="utf-8", newline="")
        return True
    return False


def main():
    vault = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else r"C:/development/echo-test-vault")
    changed = 0
    for note in (vault / "bible").glob("*/*/*.md"):
        if migrate_note(note):
            changed += 1
    print(f"linked nav in {changed} notes under {vault}")


if __name__ == "__main__":
    main()
