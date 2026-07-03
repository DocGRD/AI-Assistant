"""
Markdown-aware chunker — Milestone 11.

Splits a note body into retrieval-sized chunks (~300 tokens ≈ 1200 chars), broken
on heading and paragraph boundaries, each tagged with the nearest heading. Distinct
from watcher/content_chunker.py, which targets ~3000-token request chunks.
"""

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass
class Chunk:
    text:       str
    heading:    str
    char_start: int
    char_end:   int


def chunk_markdown(body: str, target_chars: int = 1200) -> list[Chunk]:
    """Heading-aware, size-capped chunks. Offsets are into `body`."""
    if not body or not body.strip():
        return []

    chunks: list[Chunk] = []
    heading   = ""
    cur_text  = ""
    cur_start: int | None = None
    pos = 0

    def flush(end: int) -> None:
        nonlocal cur_text, cur_start
        t = cur_text.strip()
        if t:
            chunks.append(Chunk(text=t, heading=heading,
                                char_start=cur_start if cur_start is not None else 0,
                                char_end=end))
        cur_text  = ""
        cur_start = None

    for line in body.splitlines(keepends=True):
        line_start = pos
        pos += len(line)

        m = _HEADING_RE.match(line.rstrip("\n"))
        if m:
            flush(line_start)            # a heading ends the current chunk
            heading = m.group(2).strip()
            continue

        if cur_start is None and line.strip():
            cur_start = line_start
        cur_text += line

        # Flush at a paragraph boundary once we're over target size.
        if len(cur_text) >= target_chars and line.strip() == "":
            flush(pos)

    flush(pos)
    return chunks
