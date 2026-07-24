"""One-time migration: strip BSB placeholder markers ("vvv", "-") from already-generated BSB data.

The Berean tables use "vvv" to mark an original-language word that has NO separate English word at that
position (its sense is carried inside a neighbouring word — e.g. the negative in "cannot"). Earlier runs
emitted that marker as literal reading text, so chapters showed a stray "vvv". This removes those spans
from the reading notes and blanks the gloss in the reverse interlinear, leaving the original word intact.

Idempotent. Env: BIBLE_VAULT (target vault).
"""
from __future__ import annotations

import json
import os
import pathlib
import re

VAULT = pathlib.Path(os.environ.get("BIBLE_VAULT", r"C:/development/echo-test-vault"))
PLACEHOLDERS = {"-", "vvv"}

# a tagged placeholder span plus any single space that follows it
SPAN_RE = re.compile(r'<span class="lm-s" data-s="[^"]*">(?:vvv|-)</span>[ ]?')


def fix_notes() -> tuple[int, int]:
    notes = files = 0
    for path in sorted((VAULT / "bible").glob("*/bsb/*.md")):
        text = path.read_text(encoding="utf-8")
        fixed = SPAN_RE.sub("", text)
        if fixed == text:
            continue
        # tidy spacing the removal may leave behind, on verse lines only
        out = []
        for line in fixed.split("\n"):
            if line.startswith("**"):
                line = re.sub(r"[ ]{2,}(?![ ]*$)", " ", line)   # collapse runs (keep trailing hard-breaks)
                line = re.sub(r"\s+([,.;:!?])", r"\1", line)     # no space before punctuation
            out.append(line)
        path.write_text("\n".join(out), encoding="utf-8")
        notes += len(SPAN_RE.findall(text))
        files += 1
    return notes, files


def fix_interlinear() -> tuple[int, int]:
    entries = files = 0
    for path in sorted((VAULT / "AI" / "bible-bsb").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        hits = 0
        for words in data.values():
            for w in words:
                if (w.get("e") or "").strip() in PLACEHOLDERS:
                    w["e"] = ""
                    hits += 1
        if hits:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            entries += hits
            files += 1
    return entries, files


def main() -> int:
    n, f = fix_notes()
    e, jf = fix_interlinear()
    print(f"BSB placeholders removed: {n} spans in {f} chapter notes; {e} glosses blanked in {jf} interlinear files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
