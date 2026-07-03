"""
Excalidraw text extraction — Milestone 19, Slice 1 (zero-cost, exact).

Obsidian stores an Excalidraw drawing as a `*.excalidraw.md` note whose `## Text
Elements` section already lists every typed label in plain markdown (each line may end
with a `^blockid`), followed by a `## Drawing` block of (often compressed) scene JSON.

The indexer would otherwise embed that JSON noise and miss the labels. Here we pull just
the human text so Vault QA can answer over drawings (sermon-note diagrams, mind-maps).
No OCR, no model call — pure parsing.
"""

from __future__ import annotations

import json
import re

_BLOCKID_RE = re.compile(r"\s*\^[A-Za-z0-9_-]+\s*$")   # trailing Obsidian block id


def is_excalidraw(rel_path: str, frontmatter: dict | None = None) -> bool:
    if rel_path and rel_path.lower().endswith(".excalidraw.md"):
        return True
    return bool(frontmatter and "excalidraw-plugin" in frontmatter)


def _from_text_elements(content: str) -> list[str]:
    """Lines of the `## Text Elements` section, block-ids stripped."""
    lines = content.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("## text elements"):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("#") or stripped == "%%":   # next section ends it
                break
            text = _BLOCKID_RE.sub("", line).rstrip()
            if text.strip():
                out.append(text)
    return out


def _from_drawing_json(content: str) -> list[str]:
    """Text from a plain (uncompressed) ```json drawing block, if present."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    if not m:
        return []
    try:
        scene = json.loads(m.group(1))
    except Exception:
        return []
    return [el["text"].strip()
            for el in scene.get("elements", [])
            if isinstance(el, dict) and el.get("type") == "text" and el.get("text", "").strip()]


def extract_excalidraw_text(content: str) -> str:
    """Return the drawing's human text (Text Elements section first, JSON fallback),
    de-duplicated and order-preserving. Empty string if there's nothing typed."""
    parts = _from_text_elements(content) or _from_drawing_json(content)
    seen, out = set(), []
    for p in parts:
        key = p.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(p)
    return "\n".join(out)
