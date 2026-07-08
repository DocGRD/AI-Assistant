"""
Tool: create_note — Milestone 7.5 patch 2

Changes:
  - _normalise_path() added: fixes backslashes and double-slashes.
  - _warn_suspicious_path() logs a warning when a path looks like it
    might have been generated with slashes instead of spaces (e.g.
    "My/New/Note.md" from a model that meant "My New Note.md").
    This does not block the operation — we trust the path as given —
    but the warning helps diagnose agent misbehaviour.
  - Both normalisation and the warning run before any filesystem work.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from assistant_core.tools.base_tool import BaseTool, ToolResult
from assistant_core.links import neutralize_dangling

logger = logging.getLogger("assistant")


def _normalise_path(rel_path: str) -> str:
    """
    Normalise a vault-relative path:
      - Replace backslashes with forward slashes
        (models sometimes generate Windows-style paths)
      - Collapse consecutive slashes
      - Strip leading/trailing whitespace and slashes
    """
    p = rel_path.replace("\\", "/")
    p = re.sub(r"/+", "/", p)
    return p.strip().strip("/")


def _warn_suspicious_path(rel_path: str, logger: logging.Logger) -> None:
    """
    Log a warning if a path looks like the model converted spaces to slashes.

    Heuristic: if every path component (except the last) is a single
    common English word (all alpha, 2–12 chars, no digits or hyphens),
    the model may have written "My/New/Note.md" instead of "My New Note.md".

    This is a heuristic, not a hard block — legitimate paths like
    "AI/Memory/Projects/Index.md" have short alpha components and are fine.
    We only warn when ALL non-final components match the pattern AND the
    path has no conventional vault prefix (AI/, 06/, etc.).
    """
    parts = Path(rel_path).parts
    if len(parts) < 3:
        return

    # Skip paths that start with known vault prefixes
    known_prefixes = {"ai", "01", "02", "03", "04", "05", "06", "07", "08", "09"}
    if parts[0].lower().split()[0] in known_prefixes:
        return

    # Check if all directory components look like single English words
    dir_parts = parts[:-1]   # everything except the filename
    single_words = all(
        re.match(r"^[a-zA-Z]{2,12}$", p) for p in dir_parts
    )
    if single_words and len(dir_parts) >= 2:
        reconstructed = " ".join(dir_parts) + "." + Path(parts[-1]).suffix.lstrip(".")
        logger.warning(
            f"[create_note] Suspicious path: {rel_path!r} — "
            f"did the model mean '{reconstructed}'? "
            f"Check the system prompt instruction to use hyphens in note names."
        )


class CreateNoteTool(BaseTool):
    """Creates a new Markdown note in the vault."""

    def __init__(self, vault_path: str, config: dict | None = None):
        self._vault = Path(vault_path)
        self._config = config or {}
        self._link_policy = self._config.get("link_validation", "strip")

    @property
    def name(self) -> str:
        return "create_note"

    @property
    def description(self) -> str:
        return "Create a new note in the vault. Input: first line = path, remaining lines = content."

    def run(self, input_data: str) -> ToolResult:
        lines = input_data.strip().splitlines()
        if not lines:
            return ToolResult(success=False, output="No input provided. First line must be the note path.")

        rel_path = lines[0].strip()
        content  = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        if not rel_path:
            return ToolResult(success=False, output="Note path (first line) is empty.")

        # Normalise path: fix backslashes, collapse double slashes
        rel_path = _normalise_path(rel_path)

        # Ensure .md extension
        if not rel_path.endswith(".md"):
            rel_path += ".md"

        # Warn if path looks suspicious (spaces-as-slashes model error)
        _warn_suspicious_path(rel_path, logger)

        target = self._vault / rel_path

        if target.exists():
            return ToolResult(
                success = False,
                output  = (
                    f"Note already exists: {rel_path}\n"
                    "Use vault:update to append to it, or choose a different path."
                )
            )

        target.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        if content and not content.startswith("#"):
            header  = f"# {Path(rel_path).stem}\n\n"
            content = header + content

        # M30 — strip fabricated [[links]] to notes that don't exist before writing.
        content, removed_links = neutralize_dangling(content, self._vault, self._link_policy)

        # M37 — trust on write: flag/source factual claims the vault can't support.
        from assistant_core.write_guard import guard_content
        private = bool(re.search(r"^private:\s*true", content, re.MULTILINE | re.IGNORECASE))
        content, guard_status = guard_content(self._vault, content, self._config, private=private)

        final_content = content
        if removed_links:
            final_content += "\n\n---\n*Removed unresolved links: " + ", ".join(removed_links) + "*"
            logger.info(f"[create_note] Neutralized {len(removed_links)} dangling link(s): {removed_links}")
        final_content += f"\n\n---\n*Created by Loremaster — {timestamp}*\n"

        try:
            target.write_text(final_content, encoding="utf-8")
            logger.info(f"[create_note] Created: {rel_path} ({len(final_content)} chars)")
            note = f" ({len(removed_links)} unresolved link(s) removed)" if removed_links else ""
            if guard_status == "flagged":
                note += " ⚠ unsourced claims flagged"
            return ToolResult(
                success  = True,
                output   = f"✓ Note created: {rel_path}{note}",
                metadata = {"path": rel_path, "size_chars": len(final_content),
                            "removed_links": removed_links, "guard": guard_status},
            )
        except Exception as exc:
            logger.error(f"[create_note] Failed: {exc}")
            return ToolResult(success=False, output=f"Could not create note: {exc}")
